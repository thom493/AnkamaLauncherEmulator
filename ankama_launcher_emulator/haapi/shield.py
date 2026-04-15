"""Shield detection and exceptions."""

import logging

import requests

from ankama_launcher_emulator.haapi.zaap_version import ZAAP_VERSION
from ankama_launcher_emulator.utils.proxy import to_socks5h

logger = logging.getLogger()


class ShieldRequired(Exception):
    """Raised when proxy IP needs Shield verification."""

    def __init__(self, login: str, proxy_url: str, game_id: int):
        self.login = login
        self.proxy_url = proxy_url
        self.game_id = game_id
        super().__init__(f"Shield verification required for {login} from proxy")


def check_proxy_needs_shield(api_key: str, proxy_url: str, game_id: int = 102) -> bool:
    """Test if proxy IP triggers Shield by calling SignOnWithApiKey.

    Returns True if Shield verification needed, False if proxy is already trusted.
    """
    session = requests.Session()
    h_url = to_socks5h(proxy_url)
    session.proxies = {"http": h_url, "https": h_url}

    try:
        response = session.post(
            "https://haapi.ankama.com/json/Ankama/v5/Account/SignOnWithApiKey",
            json={"game": game_id},
            headers={
                "apikey": api_key,
                "User-Agent": f"Zaap {ZAAP_VERSION}",
            },
            verify=False,
        )
        if response.status_code == 403:
            logger.info("[SHIELD] Proxy IP blocked/shielded (403)")
            return True
        response.raise_for_status()
        return False
    except requests.exceptions.HTTPError:
        return True
