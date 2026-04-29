import base64
import json
import os
from importlib.metadata import PackageNotFoundError, version
from typing import NotRequired, TypedDict

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

from ankama_launcher_emulator.consts import (
    ALT_API_KEY_FOLDER_PATH,
    ALT_CERTIFICATE_FOLDER_PATH,
    API_KEY_FOLDER_PATH,
)
from ankama_launcher_emulator.decrypter.crypto_helper import CryptoHelper
from ankama_launcher_emulator.decrypter.device import Device
from ankama_launcher_emulator.haapi.account_meta import AccountMeta
from ankama_launcher_emulator.interfaces.deciphered_api_key import DecipheredApiKeyDatas
from ankama_launcher_emulator.interfaces.deciphered_cert import DecipheredCertifDatas
from ankama_launcher_emulator.utils.proxy_store import ProxyStore

FORMAT_VERSION = 1
PBKDF2_ITERATIONS = 600_000


class PortableExchangeError(Exception):
    pass


class PortableExchangeConflictError(PortableExchangeError):
    pass


class PortableExchangePassphraseError(PortableExchangeError):
    pass


class PortableExchangeEnvelope(TypedDict):
    version: int
    cipher: str
    kdf: str
    iterations: int
    salt: str
    nonce: str
    ciphertext: str


class PortableAccountPayload(TypedDict):
    version: int
    exported_at: str
    app_version: str
    login: str
    account_id: int
    alias: str | None
    portable_mode: bool
    fake_uuid: str
    fake_hm1: str
    fake_hm2: str
    fake_hostname: str
    proxy_url: str | None
    cert_validated_proxy_url: str | None
    keydata: DecipheredApiKeyDatas
    certificate: NotRequired[DecipheredCertifDatas | None]


def _app_version() -> str:
    try:
        return version("ankama_launcher_emulator")
    except PackageNotFoundError:
        return "0.1.0"


def _b64encode(raw: bytes) -> str:
    return base64.b64encode(raw).decode("ascii")


def _b64decode(text: str, label: str) -> bytes:
    try:
        return base64.b64decode(text.encode("ascii"))
    except (ValueError, UnicodeEncodeError) as err:
        raise PortableExchangeError(f"Invalid portable account {label}") from err


def _derive_key(passphrase: str, salt: bytes) -> bytes:
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=salt,
        iterations=PBKDF2_ITERATIONS,
    )
    return kdf.derive(passphrase.encode("utf-8"))


def _ensure_non_empty_passphrase(passphrase: str) -> None:
    if not passphrase:
        raise PortableExchangePassphraseError("Passphrase is required")


def _account_exists_locally(login: str) -> bool:
    if AccountMeta().get(login) is not None:
        return True
    try:
        for acc in CryptoHelper.getStoredApiKeys(API_KEY_FOLDER_PATH, Device.getUUID()):
            if acc["apikey"]["login"].lower() == login.lower():
                return True
    except Exception:
        return False
    return False


def _cleanup_partial_import(login: str) -> None:
    AccountMeta().remove(login)
    cert_hash = CryptoHelper.createHashFromStringSha(login)
    key_dir = os.path.join(ALT_API_KEY_FOLDER_PATH, cert_hash)
    cert_dir = os.path.join(ALT_CERTIFICATE_FOLDER_PATH, cert_hash)
    for path in (
        os.path.join(key_dir, f".key{cert_hash}"),
        os.path.join(cert_dir, f".certif{cert_hash}"),
    ):
        try:
            os.unlink(path)
        except OSError:
            pass
    for folder in (key_dir, cert_dir):
        try:
            os.rmdir(folder)
        except OSError:
            pass


def _validate_payload(raw_payload: object) -> PortableAccountPayload:
    if not isinstance(raw_payload, dict):
        raise PortableExchangeError("Portable account payload is invalid")

    payload = dict(raw_payload)
    required_strs = [
        "login",
        "fake_uuid",
        "fake_hm1",
        "fake_hm2",
        "fake_hostname",
    ]
    for key in required_strs:
        value = payload.get(key)
        if not isinstance(value, str) or not value:
            raise PortableExchangeError(f"Portable account payload missing {key}")

    if payload.get("version") != FORMAT_VERSION:
        raise PortableExchangeError("Unsupported portable account payload version")
    if payload.get("portable_mode") is not True:
        raise PortableExchangeError("Portable account payload is not portable")

    keydata = payload.get("keydata")
    if not isinstance(keydata, dict):
        raise PortableExchangeError("Portable account payload missing keydata")
    if keydata.get("login") != payload["login"]:
        raise PortableExchangeError("Portable account keydata login mismatch")
    if not isinstance(keydata.get("accountId"), int):
        raise PortableExchangeError("Portable account payload missing account id")
    if not isinstance(keydata.get("key"), str) or not keydata.get("key"):
        raise PortableExchangeError("Portable account payload missing API key")

    certificate = payload.get("certificate")
    if certificate is not None:
        if not isinstance(certificate, dict):
            raise PortableExchangeError("Portable account certificate is invalid")
        if not isinstance(certificate.get("id"), int):
            raise PortableExchangeError("Portable account certificate is missing id")
        if not isinstance(certificate.get("encodedCertificate"), str):
            raise PortableExchangeError(
                "Portable account certificate is missing encodedCertificate"
            )

    alias = payload.get("alias")
    if alias is not None and not isinstance(alias, str):
        raise PortableExchangeError("Portable account alias is invalid")
    for nullable_key in ("proxy_url", "cert_validated_proxy_url"):
        value = payload.get(nullable_key)
        if value is not None and not isinstance(value, str):
            raise PortableExchangeError(f"Portable account {nullable_key} is invalid")

    return payload  # type: ignore[return-value]


def _load_envelope(input_path: str) -> PortableExchangeEnvelope:
    try:
        with open(input_path, "r", encoding="utf-8") as file:
            raw = json.load(file)
    except (OSError, json.JSONDecodeError) as err:
        raise PortableExchangeError("Portable account file is unreadable") from err

    if not isinstance(raw, dict):
        raise PortableExchangeError("Portable account file is invalid")
    if raw.get("version") != FORMAT_VERSION:
        raise PortableExchangeError("Unsupported portable account file version")
    return raw  # type: ignore[return-value]


def inspect_portable_account(
    input_path: str, passphrase: str
) -> PortableAccountPayload:
    _ensure_non_empty_passphrase(passphrase)
    envelope = _load_envelope(input_path)
    if envelope.get("cipher") != "AESGCM" or envelope.get("kdf") != "PBKDF2-SHA256":
        raise PortableExchangeError("Unsupported portable account protection format")
    if envelope.get("iterations") != PBKDF2_ITERATIONS:
        raise PortableExchangeError("Unsupported portable account key derivation")

    salt = _b64decode(str(envelope.get("salt", "")), "salt")
    nonce = _b64decode(str(envelope.get("nonce", "")), "nonce")
    ciphertext = _b64decode(str(envelope.get("ciphertext", "")), "ciphertext")
    key = _derive_key(passphrase, salt)

    try:
        decrypted = AESGCM(key).decrypt(nonce, ciphertext, None)
    except InvalidTag as err:
        raise PortableExchangePassphraseError(
            "Invalid passphrase or corrupted portable account file"
        ) from err

    try:
        payload = json.loads(decrypted.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as err:
        raise PortableExchangeError("Portable account payload is invalid") from err
    return _validate_payload(payload)


def export_portable_account(
    login: str,
    passphrase: str,
    output_path: str,
    proxy_store: ProxyStore,
) -> str:
    _ensure_non_empty_passphrase(passphrase)
    meta = AccountMeta()
    entry = meta.get(login)
    if entry is None:
        raise PortableExchangeError("Only managed accounts can be exported")
    if not entry.get("portable_mode"):
        raise PortableExchangeError("Only portable accounts can be exported")

    uuid_active, cert_folder, key_folder, _, _ = CryptoHelper.get_crypto_context(login)
    try:
        keydata = CryptoHelper.getStoredApiKey(login, key_folder, uuid_active)["apikey"]
    except StopIteration as err:
        raise PortableExchangeError("Portable account keydata is missing") from err

    certificate: DecipheredCertifDatas | None = None
    try:
        certificate = CryptoHelper.getStoredCertificate(
            login, cert_folder, uuid_active
        )["certificate"]
    except (FileNotFoundError, OSError):
        certificate = None

    payload: PortableAccountPayload = {
        "version": FORMAT_VERSION,
        "exported_at": __import__("datetime").datetime.now().isoformat(),
        "app_version": _app_version(),
        "login": login,
        "account_id": int(keydata["accountId"]),
        "alias": entry.get("alias"),
        "portable_mode": True,
        "fake_uuid": str(entry.get("fake_uuid") or ""),
        "fake_hm1": str(entry.get("fake_hm1") or ""),
        "fake_hm2": str(entry.get("fake_hm2") or ""),
        "fake_hostname": str(entry.get("fake_hostname") or ""),
        "proxy_url": proxy_store.get_proxy_url(login),
        "cert_validated_proxy_url": entry.get("cert_validated_proxy_url"),
        "keydata": keydata,
        "certificate": certificate,
    }
    payload = _validate_payload(payload)

    salt = os.urandom(16)
    nonce = os.urandom(12)
    key = _derive_key(passphrase, salt)
    ciphertext = AESGCM(key).encrypt(
        nonce,
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8"),
        None,
    )
    envelope: PortableExchangeEnvelope = {
        "version": FORMAT_VERSION,
        "cipher": "AESGCM",
        "kdf": "PBKDF2-SHA256",
        "iterations": PBKDF2_ITERATIONS,
        "salt": _b64encode(salt),
        "nonce": _b64encode(nonce),
        "ciphertext": _b64encode(ciphertext),
    }

    output_dir = os.path.dirname(output_path)
    if output_dir:
        os.makedirs(output_dir, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as file:
        json.dump(envelope, file, indent=2)
    return login


def import_portable_account(
    input_path: str,
    passphrase: str,
    proxy_store: ProxyStore,
) -> str:
    payload = inspect_portable_account(input_path, passphrase)
    login = payload["login"]
    if _account_exists_locally(login):
        raise PortableExchangeConflictError(
            f"Account {login} already exists. Remove it before importing."
        )

    meta = AccountMeta()
    meta.set_imported_portable_profile(
        login,
        alias=payload.get("alias"),
        fake_uuid=payload["fake_uuid"],
        fake_hm1=payload["fake_hm1"],
        fake_hm2=payload["fake_hm2"],
        fake_hostname=payload["fake_hostname"],
        proxy_url=payload.get("proxy_url"),
        cert_validated_proxy_url=payload.get("cert_validated_proxy_url"),
    )

    try:
        uuid_active, cert_folder, key_folder, _, _ = CryptoHelper.get_crypto_context(
            login
        )
        cert_hash = CryptoHelper.createHashFromStringSha(login)
        CryptoHelper.encryptToFile(
            os.path.join(key_folder, f".key{cert_hash}"),
            payload["keydata"],
            uuid_active,
        )

        certificate = payload.get("certificate")
        if certificate is not None:
            cert_to_store = dict(certificate)
            cert_to_store["login"] = login
            CryptoHelper.encryptToFile(
                os.path.join(cert_folder, f".certif{cert_hash}"),
                cert_to_store,
                uuid_active,
            )
    except Exception:
        _cleanup_partial_import(login)
        raise

    proxy_url = payload.get("proxy_url")
    if proxy_url:
        proxy_id = next(
            (
                pid
                for pid, entry in proxy_store.list_proxies().items()
                if entry.url == proxy_url
            ),
            None,
        )
        if proxy_id is None:
            proxy_id = proxy_store.add_proxy(proxy_url[:40], proxy_url)
        proxy_store.assign_proxy(login, proxy_id)
    else:
        proxy_store.assign_proxy(login, None)

    return login
