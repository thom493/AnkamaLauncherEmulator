import logging
import os
import time

from ankama_launcher_emulator.decrypter.crypto_helper import CryptoHelper
from ankama_launcher_emulator.haapi.account_meta import AccountMeta

logger = logging.getLogger()


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

    uuid_active, _, key_folder, _, _ = CryptoHelper.get_crypto_context(login)

    file_name = ".key" + CryptoHelper.createHashFromStringSha(login)
    file_path = os.path.join(key_folder, file_name)
    CryptoHelper.encryptToFile(file_path, keydata, uuid_active)

    meta = AccountMeta()
    meta.set_meta(login, source="managed", alias=alias)


def list_all_api_keys() -> list:
    """Enumerate all known accounts across portable + official keydata folders.

    Source of truth: AccountMeta (each entry resolves to its own crypto context).
    Also scans the official folder for pre-meta legacy files.
    """
    from ankama_launcher_emulator.consts import API_KEY_FOLDER_PATH
    from ankama_launcher_emulator.decrypter.device import Device
    from ankama_launcher_emulator.haapi.account_meta import AccountMeta

    seen: set[str] = set()
    results: list = []

    meta = AccountMeta()
    for login in meta.all_entries():
        try:
            uuid_active, _, key_folder, _, _ = CryptoHelper.get_crypto_context(login)
            results.append(CryptoHelper.getStoredApiKey(login, key_folder, uuid_active))
            seen.add(login)
        except (StopIteration, FileNotFoundError, OSError) as err:
            logger.warning(f"[LOAD] Skip {login}: {err}")

    try:
        for acc in CryptoHelper.getStoredApiKeys(API_KEY_FOLDER_PATH, Device.getUUID()):
            login = acc["apikey"]["login"]
            if login not in seen:
                results.append(acc)
                seen.add(login)
    except (FileNotFoundError, OSError) as err:
        logger.warning(f"[LOAD] Official folder scan failed: {err}")

    return results


def persist_token_refresh(
    login: str,
    access_token: str,
    refresh_token: str | None,
) -> None:
    """Persist refreshed API key + refresh token to the account's active keydata file.

    Mode-aware via get_crypto_context (portable vs official path).
    If refresh_token is None, keeps the existing stored refreshToken.
    """
    uuid_active, _, key_folder, _, _ = CryptoHelper.get_crypto_context(login)
    try:
        stored = CryptoHelper.getStoredApiKey(login, key_folder, uuid_active)
    except StopIteration:
        logger.warning(f"[TOKEN_REFRESH] No keydata for {login}, cannot persist")
        return

    apikey_data = stored["apikey"]
    apikey_data["key"] = access_token
    if refresh_token:
        apikey_data["refreshToken"] = refresh_token
    apikey_data["refreshDate"] = int(time.time() * 1000)

    file_path = os.path.join(key_folder, stored["apikeyFile"])
    CryptoHelper.encryptToFile(file_path, apikey_data, uuid_active)
    logger.info(f"[TOKEN_REFRESH] Tokens persisted for {login} at {key_folder}")
