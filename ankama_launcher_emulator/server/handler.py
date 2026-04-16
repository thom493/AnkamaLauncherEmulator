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
        try:
            certificate_datas = CryptoHelper.getStoredCertificate(login)["certificate"]
        except FileNotFoundError:
            certificate_datas = None
        meta = AccountMeta()
        hm1 = meta.get_hm1(login)
        hm2 = meta.get_hm2(login)
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
