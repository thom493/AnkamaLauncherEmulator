import json
import logging
from dataclasses import dataclass, field
from threading import Timer
from typing import Callable

from ankama_launcher_emulator.decrypter.crypto_helper import (
    CryptoHelper,
)
from ankama_launcher_emulator.haapi.account_meta import AccountMeta
from ankama_launcher_emulator.haapi.haapi import (
    get_account_info_by_login,
)
from ankama_launcher_emulator.haapi.shield import ShieldRecoveryRequired
from ankama_launcher_emulator.interfaces.account_game_info import (
    AccountGameInfo,
)
from ankama_launcher_emulator.utils.internet import (
    retry_internet,
)

logger = logging.getLogger()


@dataclass
class AnkamaLauncherHandler:
    infos_by_hash: dict[str, AccountGameInfo] = field(
        init=False, default_factory=lambda: {}
    )
    _timer: list[Timer] = field(init=False, default_factory=list)
    on_shield_recovery: Callable[[str], None] | None = field(
        init=False, default=None, repr=False
    )

    @retry_internet
    def connect(
        self, gameName: str, releaseName: str, instanceId: int, hash: str
    ) -> str:
        logger.info(f"connect hash {hash}")
        return hash

    @retry_internet
    def userInfo_get(self, hash: str) -> str:
        logger.info(f"userInfo_get {hash}")
        account_info = get_account_info_by_login(self.infos_by_hash[hash].haapi.login)
        if account_info is not None:
            return json.dumps(account_info)
        raise ValueError("<!> Account info not found in settings !")

    @retry_internet
    def settings_get(self, hash: str, key: str) -> str:
        logger.info(f"settings_get {hash}")
        match key:
            case "autoConnectType":
                return '"2"'
            case "language":
                return '"fr"'
            case "connectionPort":
                return '"5555"'
        raise NotImplementedError

    @retry_internet
    def auth_getGameToken(self, hash: str, gameId: int) -> str:
        logger.info(f"auth_getGameToken {hash}")
        login = self.infos_by_hash[hash].login
        
        meta = AccountMeta()
        entry = meta.get(login) or {}
        portable = entry.get("portable_mode", False)
        
        from ankama_launcher_emulator.consts import (
            CERTIFICATE_FOLDER_PATH, ALT_CERTIFICATE_FOLDER_PATH,
            API_KEY_FOLDER_PATH, ALT_API_KEY_FOLDER_PATH
        )
        from ankama_launcher_emulator.decrypter.device import Device
        import os
        
        real_uuid = Device.getUUID()
        fake_uuid = entry.get("fake_uuid")
        
        if portable and fake_uuid:
            uuid_to_use = fake_uuid
            cert_folder = ALT_CERTIFICATE_FOLDER_PATH
            key_folder = ALT_API_KEY_FOLDER_PATH
            hm1 = entry.get("fake_hm1")
            hm2 = entry.get("fake_hm2")
            
            try:
                CryptoHelper.getStoredApiKey(login, key_folder, uuid_to_use)
            except StopIteration:
                try:
                    official_key = CryptoHelper.getStoredApiKey(login, API_KEY_FOLDER_PATH, real_uuid)
                    file_path = os.path.join(key_folder, official_key["apikeyFile"])
                    CryptoHelper.encryptToFile(file_path, official_key["apikey"], uuid_to_use)
                    logger.info(f"[MIGRATION] Keydata sandboxed for {login}")
                except StopIteration:
                    pass
        else:
            uuid_to_use = real_uuid
            cert_folder = CERTIFICATE_FOLDER_PATH
            key_folder = API_KEY_FOLDER_PATH
            hm1, hm2 = CryptoHelper.createHmEncoders()
            
        try:
            certificate_datas = CryptoHelper.getStoredCertificate(login, cert_folder, uuid_to_use)["certificate"]
        except (FileNotFoundError, IOError):
            certificate_datas = None
            
        try:
            return self.infos_by_hash[hash].haapi.createToken(
                gameId, certificate_datas, hm1=hm1, hm2=hm2
            )
        except ShieldRecoveryRequired as err:
            if self.on_shield_recovery is not None:
                self.on_shield_recovery(err.login)
            raise

    @retry_internet
    def updater_isUpdateAvailable(self, gameSession: str):
        logger.info(f"updater_isUpdateAvailable {gameSession}")
        return False

    @retry_internet
    def zaapMustUpdate_get(self, gameSession: str) -> bool:
        logger.info(f"zaapMustUpdate_get {gameSession}")
        return False
