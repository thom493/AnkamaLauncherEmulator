"""Shield detection and HAAPI-based verification flow.

Matches the official Zaap launcher protocol:
  1. Detect Shield via SignOnWithApiKey returning 403
  2. PKCE re-login for fresh API key
  3. GET /Shield/SecurityCode?transportType=EMAIL with fresh key
  4. User enters email code
  5. GET /Shield/ValidateCode?game_id=102&code=X&hm1=X&hm2=X&name=X
  6. Store returned certificate
"""

import getpass
import logging

import requests

from ankama_launcher_emulator.decrypter.crypto_helper import CryptoHelper
from ankama_launcher_emulator.haapi.urls import (
    ANKAMA_SHIELD_SECURITY_CODE,
    ANKAMA_SHIELD_VALIDATE_CODE,
)
from ankama_launcher_emulator.haapi.zaap_version import ZAAP_VERSION
from ankama_launcher_emulator.utils.debug_logger import hook_session
from ankama_launcher_emulator.utils.proxy import to_socks5h

logger = logging.getLogger()


class ShieldRequired(Exception):
    """Raised when proxy IP needs Shield verification."""

    def __init__(self, login: str, proxy_url: str):
        self.login = login
        self.proxy_url = proxy_url
        super().__init__(f"Shield verification required for {login} from proxy")


def _make_session(proxy_url: str | None = None) -> requests.Session:
    session = requests.Session()
    if proxy_url:
        h_url = to_socks5h(proxy_url)
        session.proxies = {"http": h_url, "https": h_url}
    hook_session(session)
    return session


def _zaap_headers(api_key: str) -> dict:
    return {
        "apikey": api_key,
        "User-Agent": f"Zaap {ZAAP_VERSION}",
        "accept": "*/*",
        "accept-encoding": "gzip,deflate",
        "accept-language": "fr",
    }


def check_proxy_needs_shield(api_key: str, proxy_url: str) -> bool:
    """Test if proxy IP triggers Shield by calling SignOnWithApiKey.

    Returns True if Shield verification needed, False if proxy is already trusted.
    """
    session = _make_session(proxy_url)
    try:
        response = session.post(
            "https://haapi.ankama.com/json/Ankama/v5/Account/SignOnWithApiKey",
            json={"game": 102},
            headers=_zaap_headers(api_key),
            verify=False,
        )
        if response.status_code == 403:
            logger.info("[SHIELD] Proxy IP blocked/shielded (403)")
            return True
        response.raise_for_status()
        return False
    except requests.exceptions.HTTPError:
        return True


def get_account(api_key: str) -> dict:
    """GET /Account/Account with the given API key.

    Returns account info including 'security' field.
    """
    session = _make_session()
    response = session.get(
        "https://haapi.ankama.com/json/Ankama/v5/Account/Account",
        headers=_zaap_headers(api_key),
        verify=False,
    )
    response.raise_for_status()
    return response.json()


def account_needs_shield(api_key: str) -> bool:
    """Check if account's security field includes SHIELD."""
    try:
        account = get_account(api_key)
        security = account.get("security", [])
        needs = "SHIELD" in security or "UNSECURED" in security
        logger.info(f"[SHIELD] Account security={security}, needs_shield={needs}")
        return needs
    except Exception as err:
        logger.warning(f"[SHIELD] getAccount failed: {err}, assuming Shield needed")
        return True


def request_security_code(
    api_key: str,
    transport_type: str = "EMAIL",
) -> dict:
    """Request Ankama to send a security code via email.

    GET /Shield/SecurityCode?transportType=EMAIL
    Returns the response body dict on success.
    """
    session = _make_session()
    headers = _zaap_headers(api_key)

    response = session.get(
        ANKAMA_SHIELD_SECURITY_CODE,
        params={"transportType": transport_type},
        headers=headers,
        verify=False,
    )
    logger.info(
        f"[SHIELD] SecurityCode: status={response.status_code} "
        f"body={response.text[:500]}"
    )
    response.raise_for_status()
    return response.json()


def validate_security_code(
    api_key: str,
    code: str,
    hm1: str | None = None,
    hm2: str | None = None,
) -> dict:
    """Validate the security code with full params matching official launcher.

    GET /Shield/ValidateCode?game_id=102&code=X&hm1=X&hm2=X&name=launcher-USER
    Returns certificate data on success.

    If hm1/hm2 not provided, uses machine-derived values.
    """
    session = _make_session()
    headers = _zaap_headers(api_key)
    if not hm1 or not hm2:
        hm1, hm2 = CryptoHelper.createHmEncoders()
    username = getpass.getuser()

    params = {
        "game_id": 102,
        "code": code,
        "hm1": hm1,
        "hm2": hm2,
        "name": f"launcher-{username}",
    }

    response = session.get(
        ANKAMA_SHIELD_VALIDATE_CODE,
        params=params,
        headers=headers,
        verify=False,
    )
    logger.info(
        f"[SHIELD] ValidateCode: status={response.status_code} "
        f"body={response.text[:500]}"
    )
    response.raise_for_status()
    return response.json()


def store_shield_certificate(login: str, cert_data: dict) -> None:
    """Store the certificate returned by ValidateCode."""
    import os

    from ankama_launcher_emulator.consts import CERTIFICATE_FOLDER_PATH
    from ankama_launcher_emulator.decrypter.device import Device

    cert_data["login"] = login
    file_path = os.path.join(
        CERTIFICATE_FOLDER_PATH,
        ".certif" + CryptoHelper.createHashFromStringSha(login),
    )
    uuid = Device.getUUID()
    CryptoHelper.encryptToFile(file_path, cert_data, uuid)
    logger.info(f"[SHIELD] Certificate stored for {login}")
