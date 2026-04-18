import base64
import getpass
import hashlib
import json
import os
from typing import Any

from Cryptodome.Cipher import AES
from Cryptodome.Util.Padding import pad, unpad

from ankama_launcher_emulator.consts import (
    API_KEY_FOLDER_PATH,
    CERTIFICATE_FOLDER_PATH,
)
from ankama_launcher_emulator.decrypter.device import Device
from ankama_launcher_emulator.interfaces.deciphered_api_key import (
    DecipheredApiKey,
    DecipheredApiKeyDatas,
)
from ankama_launcher_emulator.interfaces.deciphered_cert import (
    DecipheredCertifDatas,
    StoredCertificate,
)


class CryptoHelper:
    @staticmethod
    def get_crypto_context(login: str) -> tuple[str, str, str, str, str]:
        """Returns (uuid_to_use, cert_folder, key_folder, hm1, hm2) depending on portable mode.

        Portable accounts get an isolated `{ALT_*}/{sha256(login)[:32]}/`
        subfolder so cross-account ciphertext can never collide during
        folder scans (each subfolder holds exactly one account's files,
        encrypted with that account's fake_uuid).
        """
        from ankama_launcher_emulator.haapi.account_meta import AccountMeta
        from ankama_launcher_emulator.decrypter.device import Device
        from ankama_launcher_emulator.consts import (
            CERTIFICATE_FOLDER_PATH, ALT_CERTIFICATE_FOLDER_PATH,
            API_KEY_FOLDER_PATH, ALT_API_KEY_FOLDER_PATH
        )
        meta = AccountMeta()
        entry = meta.get(login) or {}
        portable = entry.get("portable_mode", False)
        fake_uuid = entry.get("fake_uuid")

        if portable and fake_uuid:
            sub = CryptoHelper.createHashFromStringSha(login)
            cert_dir = os.path.join(ALT_CERTIFICATE_FOLDER_PATH, sub)
            key_dir = os.path.join(ALT_API_KEY_FOLDER_PATH, sub)
            os.makedirs(cert_dir, exist_ok=True)
            os.makedirs(key_dir, exist_ok=True)
            CryptoHelper._migrate_flat_to_subfolder(login, ALT_API_KEY_FOLDER_PATH, key_dir, ".key")
            CryptoHelper._migrate_flat_to_subfolder(login, ALT_CERTIFICATE_FOLDER_PATH, cert_dir, ".certif")
            return (fake_uuid, cert_dir, key_dir,
                    str(entry.get("fake_hm1") or ""), str(entry.get("fake_hm2") or ""))

        hm1, hm2 = CryptoHelper.createHmEncoders()
        return Device.getUUID(), CERTIFICATE_FOLDER_PATH, API_KEY_FOLDER_PATH, hm1, hm2

    @staticmethod
    def _migrate_flat_to_subfolder(login: str, flat_dir: str, sub_dir: str, prefix: str) -> None:
        """Move a legacy flat-layout portable file into its per-account subfolder.

        Pre-D portable layout wrote `{ALT_*}/{prefix}{sha(login)}` directly
        in the shared ALT folder. After D, the canonical path is
        `{ALT_*}/{sha(login)}/{prefix}{sha(login)}`. Rename in place if
        the flat file exists and the subfolder slot is empty.
        """
        import logging
        name = prefix + CryptoHelper.createHashFromStringSha(login)
        src = os.path.join(flat_dir, name)
        dst = os.path.join(sub_dir, name)
        if not os.path.isfile(src) or os.path.exists(dst):
            return
        try:
            os.replace(src, dst)
            logging.getLogger().info(
                f"[MIGRATE] {login}: moved {name} from flat ALT folder into per-account subfolder"
            )
        except OSError as err:
            logging.getLogger().warning(
                f"[MIGRATE] {login}: failed to move {name}: {err!r}"
            )
    @staticmethod
    def getStoredCertificate(login: str, cert_folder_path: str, uuid_auth: str) -> StoredCertificate:
        file_path = os.path.join(
            cert_folder_path,
            ".certif" + CryptoHelper.createHashFromStringSha(login),
        )
        return {
            "certificate": CryptoHelper.decryptFromFile(file_path, uuid_auth),
            "filepath": file_path,
        }

    @staticmethod
    def getStoredApiKeys(api_key_folder_path: str, uuid_auth: str) -> list[DecipheredApiKey]:
        # Portable mode parks multiple accounts in one ALT folder, each
        # encrypted with its own fake_uuid. Iterating with one uuid is
        # expected to hit cross-account ciphertext — skip files that don't
        # decrypt instead of aborting the whole scan.
        deciphered_apikeys: list[DecipheredApiKey] = []
        for apikey_file in os.listdir(api_key_folder_path):
            if not apikey_file.startswith(".key"):
                continue
            full_path = os.path.join(api_key_folder_path, apikey_file)
            if not os.path.isfile(full_path):
                continue
            try:
                apikey_data: DecipheredApiKeyDatas = CryptoHelper.decryptFromFile(
                    full_path, uuid_auth
                )
            except (ValueError, json.JSONDecodeError, UnicodeDecodeError):
                continue
            deciphered_apikeys.append(
                {"apikeyFile": apikey_file, "apikey": apikey_data}
            )
        return deciphered_apikeys

    @staticmethod
    def getStoredApiKey(login: str, api_key_folder_path: str, uuid_auth: str) -> DecipheredApiKey:
        return next(
            deciphered_api_key
            for deciphered_api_key in CryptoHelper.getStoredApiKeys(api_key_folder_path, uuid_auth)
            if deciphered_api_key["apikey"]["login"] == login
        )



    @staticmethod
    def decryptFromFile(file_path: str, uuid: str):
        with open(file_path, "r", encoding="utf-8") as file:
            data = file.read()
        return CryptoHelper.decrypt(data, uuid)

    @staticmethod
    def decrypt(data: str, uuid: str) -> Any:
        splitted_datas = data.split("|")
        iv = bytes.fromhex(splitted_datas[0])
        data_to_decrypt = bytes.fromhex(splitted_datas[1])

        key = CryptoHelper.createHashFromString(uuid)

        decipher = AES.new(key, AES.MODE_CBC, iv)

        decrypted_data = decipher.decrypt(data_to_decrypt)
        decrypted_data = unpad(decrypted_data, AES.block_size)
        return json.loads(decrypted_data.decode("utf-8"))

    @staticmethod
    def encrypt(json_obj: Any, uuid: str) -> str:
        key = CryptoHelper.createHashFromString(uuid)
        iv = os.urandom(16)
        cipher = AES.new(key, AES.MODE_CBC, iv)

        encrypted_data = json.dumps(json_obj).encode("utf-8")
        padded_data = pad(encrypted_data, AES.block_size)

        encrypted_data = cipher.encrypt(padded_data)

        return iv.hex() + "|" + encrypted_data.hex()

    @staticmethod
    def createHashFromStringSha(string: str):
        return hashlib.sha256(string.encode("utf-8")).hexdigest()[:32]

    @staticmethod
    def createHashFromString(string: str):
        return hashlib.md5(string.encode("utf-8")).digest()

    @staticmethod
    def createHmEncoders():
        arch = Device.getArch()
        plt = Device.getPlatform()
        machine_id = Device.getMachineId(plt, arch)
        username = getpass.getuser()
        os_version = Device.getOsVersion()
        ram = Device.getComputerRam()
        
        # Parity with C# float.ToString(CultureInfo.InvariantCulture) mapping
        os_version_str = str(int(os_version)) if float(os_version).is_integer() else str(os_version)

        machine_infos = [
            arch,
            plt,
            machine_id,
            username,
            os_version_str,
            str(ram),
        ]
        hm1 = CryptoHelper.createHashFromStringSha("".join(machine_infos))
        hm2 = hm1[::-1]
        return hm1, hm2

    @staticmethod
    def generateHashFromCertif(
        certif: DecipheredCertifDatas,
        hm1: str | None = None,
        hm2: str | None = None,
    ):
        if not hm1 or not hm2:
            hm1, hm2 = CryptoHelper.createHmEncoders()

        decipher = AES.new(hm2.encode(), AES.MODE_ECB)

        decoded_certificate = base64.b64decode(certif["encodedCertificate"])
        decrypted_certificate = decipher.decrypt(decoded_certificate)

        try:
            decrypted_certificate = unpad(decrypted_certificate, AES.block_size)
        except ValueError:
            pass

        combined_datas = hm1.encode() + decrypted_certificate
        return hashlib.sha256(combined_datas).hexdigest()

    @staticmethod
    def encryptToFile(file_path, json_obj, uuid):
        encrypted_json_obj = CryptoHelper.encrypt(json_obj, uuid)
        with open(file_path, "w", encoding="utf-8") as file:
            file.write(encrypted_json_obj)
