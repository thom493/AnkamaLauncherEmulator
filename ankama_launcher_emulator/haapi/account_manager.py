"""Account removal matching official Zaap cascade.

Flow: delete API key server-side → delete keydata file → delete certificate → remove metadata.
"""

import logging
import os

import requests

from ankama_launcher_emulator.consts import (
    API_KEY_FOLDER_PATH,
    ALT_API_KEY_FOLDER_PATH,
    CERTIFICATE_FOLDER_PATH,
    ALT_CERTIFICATE_FOLDER_PATH,
)
from ankama_launcher_emulator.decrypter.crypto_helper import CryptoHelper
from ankama_launcher_emulator.decrypter.device import Device
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
                    "APIKEY": api_key,
                    "User-Agent": f"Zaap {ZAAP_VERSION}",
                },
                verify=False,
            )
            logger.info(f"[REMOVE] Server-side key deleted for {login}")
        except Exception as err:
            logger.warning(f"[REMOVE] Server-side key deletion failed: {err}")

    # 2+3. Delete key + cert from ALL possible locations.
    # Files may be in official or portable paths depending on which mode was
    # active when they were written. Toggling the portable switch after account
    # creation leaves files in the old location, so we must try both.
    meta_entry = AccountMeta().get(login) or {}
    fake_uuid = meta_entry.get("fake_uuid")
    cert_hash = CryptoHelper.createHashFromStringSha(login)
    sub = cert_hash  # sha256(login)[:32] — same value used for subfolder name

    locations: list[tuple[str, str, str]] = []  # (key_folder, uuid_auth, cert_folder)

    # Official paths — always attempt
    try:
        locations.append((API_KEY_FOLDER_PATH, Device.getUUID(), CERTIFICATE_FOLDER_PATH))
    except Exception as err:
        logger.warning(f"[REMOVE] Cannot resolve official uuid: {err}")

    # Portable per-account subfolder — only if fake profile exists
    if fake_uuid:
        locations.append((
            os.path.join(ALT_API_KEY_FOLDER_PATH, sub),
            fake_uuid,
            os.path.join(ALT_CERTIFICATE_FOLDER_PATH, sub),
        ))

    for key_folder, uuid_auth, cert_folder in locations:
        try:
            stored = CryptoHelper.getStoredApiKey(login, key_folder, uuid_auth)
            os.unlink(os.path.join(key_folder, stored["apikeyFile"]))
            logger.info(f"[REMOVE] Deleted key from {key_folder}")
        except (StopIteration, FileNotFoundError, OSError) as err:
            logger.debug(f"[REMOVE] Key not in {key_folder}: {err}")

        try:
            os.unlink(os.path.join(cert_folder, f".certif{cert_hash}"))
            logger.info(f"[REMOVE] Deleted cert from {cert_folder}")
        except (FileNotFoundError, OSError) as err:
            logger.debug(f"[REMOVE] Cert not in {cert_folder}: {err}")

    # 4. Remove metadata
    AccountMeta().remove(login)
    logger.info(f"[REMOVE] Account {login} removed")
