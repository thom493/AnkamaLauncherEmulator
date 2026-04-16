import os
import time

from ankama_launcher_emulator.consts import API_KEY_FOLDER_PATH
from ankama_launcher_emulator.decrypter.crypto_helper import CryptoHelper
from ankama_launcher_emulator.decrypter.device import Device
from ankama_launcher_emulator.haapi.account_meta import AccountMeta


def persist_managed_account(
    login: str,
    account_id: int,
    access_token: str,
    refresh_token: str | None,
    *,
    alias: str | None = None,
    hm1: str | None = None,
) -> None:
    keydata = {
        "key": access_token,
        "provider": "ankama",
        "refreshToken": refresh_token or "",
        "isStayLoggedIn": True,
        "accountId": account_id,
        "login": login,
        "refreshDate": int(time.time() * 1000),
    }

    file_name = ".key" + CryptoHelper.createHashFromStringSha(login)
    file_path = os.path.join(API_KEY_FOLDER_PATH, file_name)
    CryptoHelper.encryptToFile(file_path, keydata, Device.getUUID())

    meta = AccountMeta()
    meta.set_meta(login, source="managed", alias=alias)
    meta.set_hm1(login, hm1)
