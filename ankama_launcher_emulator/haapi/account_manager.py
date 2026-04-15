"""Account removal matching official Zaap cascade.

Flow: delete API key server-side → delete keydata file → delete certificate → remove metadata.
"""

import logging
import os

import requests

from ankama_launcher_emulator.consts import (
    API_KEY_FOLDER_PATH,
    CERTIFICATE_FOLDER_PATH,
)
from ankama_launcher_emulator.decrypter.crypto_helper import CryptoHelper
from ankama_launcher_emulator.haapi.account_meta import AccountMeta
from ankama_launcher_emulator.haapi.urls import ANKAMA_API_DELETE_API_KEY
from ankama_launcher_emulator.haapi.zaap_version import ZAAP_VERSION

logger = logging.getLogger()


def remove_account(login: str, api_key: str | None = None) -> None:
    """Remove account matching official Zaap cascade.

    1. Delete API key server-side (best-effort)
    2. Delete keydata file
    3. Delete certificate file
    4. Remove AccountMeta entry
    """
    # 1. Server-side API key revocation (best-effort)
    if api_key:
        try:
            requests.delete(
                ANKAMA_API_DELETE_API_KEY,
                headers={
                    "apikey": api_key,
                    "User-Agent": f"Zaap {ZAAP_VERSION}",
                },
                verify=False,
            )
            logger.info(f"[REMOVE] Server-side key deleted for {login}")
        except Exception as err:
            logger.warning(f"[REMOVE] Server-side key deletion failed: {err}")

    # 2. Delete keydata file
    try:
        stored = CryptoHelper.getStoredApiKey(login)
        file_path = os.path.join(API_KEY_FOLDER_PATH, stored["apikeyFile"])
        os.unlink(file_path)
        logger.info(f"[REMOVE] Deleted keydata {stored['apikeyFile']}")
    except (StopIteration, FileNotFoundError, OSError) as err:
        logger.warning(f"[REMOVE] Keydata deletion: {err}")

    # 3. Delete certificate file
    try:
        cert_hash = CryptoHelper.createHashFromStringSha(login)
        cert_path = os.path.join(CERTIFICATE_FOLDER_PATH, f".certif{cert_hash}")
        os.unlink(cert_path)
        logger.info(f"[REMOVE] Deleted certificate for {login}")
    except (FileNotFoundError, OSError) as err:
        logger.warning(f"[REMOVE] Certificate deletion: {err}")

    # 4. Remove metadata
    AccountMeta().remove(login)
    logger.info(f"[REMOVE] Account {login} removed")
