import json
import logging
from dataclasses import dataclass
from typing import Any

import requests
import urllib3

from ankama_launcher_emulator.utils.internet import InterfaceAdapter
from ankama_launcher_emulator.utils.proxy import to_socks5h

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

from ankama_launcher_emulator.consts import SETTINGS_PATH
from ankama_launcher_emulator.decrypter.crypto_helper import (
    CryptoHelper,
)
from ankama_launcher_emulator.haapi.urls import (
    ANKAMA_ACCOUNT_CREATE_TOKEN,
    ANKAMA_ACCOUNT_SIGN_ON_WITH_API_KEY,
    ANKAMA_API_REFRESH_API_KEY,
)
from ankama_launcher_emulator.haapi.zaap_version import (
    ZAAP_VERSION,
)
from ankama_launcher_emulator.interfaces.deciphered_cert import (
    DecipheredCertifDatas,
)
from ankama_launcher_emulator.utils.internet import (
    retry_internet,
)


def get_account_info_by_login(login: str):
    with open(SETTINGS_PATH, "r") as file:
        content = json.load(file)
    account = next(
        (acc for acc in content["USER_ACCOUNTS"] if acc["login"] == login), None
    )
    return account


logger = logging.getLogger()


@dataclass
class Haapi:
    api_key: str
    login: str
    interface_ip: str | None
    proxy_url: str | None
    refresh_token: str | None = None

    def __post_init__(self):
        self.zaap_session = requests.Session()
        if self.proxy_url:
            h_url = to_socks5h(self.proxy_url)
            self.zaap_session.proxies = {
                "http": h_url,
                "https": h_url,
            }
        if self.interface_ip:
            adapter = InterfaceAdapter(self.interface_ip)
            self.zaap_session.mount("https://", adapter)
            self.zaap_session.mount("http://", adapter)
        self.zaap_headers = {
            "apikey": self.api_key,
            "if-none-match": "null",
            "user-Agent": f"Zaap {ZAAP_VERSION}",
            "accept": "*/*",
            "accept-encoding": "gzip,deflate",
            "sec-fetch-site": "none",
            "sec-fetch-mode": "no-cors",
            "sec-fetch-dest": "empty",
            "accept-language": "fr",
        }
        self.zaap_session.headers.update(self.zaap_headers)

    @retry_internet
    def signOnWithApiKey(self, game_id: int) -> dict[str, Any]:
        """get users infos"""
        url = ANKAMA_ACCOUNT_SIGN_ON_WITH_API_KEY
        response = self.zaap_session.post(url, json={"game": game_id}, verify=False)
        response.raise_for_status()
        body = response.json()
        return body

    @retry_internet
    def refreshApiKey(self) -> None:
        if not self.refresh_token:
            return
        url = ANKAMA_API_REFRESH_API_KEY
        response = self.zaap_session.post(
            url,
            data=f"refresh_token={self.refresh_token}&long_life_token=true",
            headers={"content-type": "text/plain;charset=UTF-8"},
            verify=False,
        )
        response.raise_for_status()

    @retry_internet
    def createToken(self, game_id: int, certif: DecipheredCertifDatas | None) -> str:
        self.refreshApiKey()
        url = ANKAMA_ACCOUNT_CREATE_TOKEN
        params: dict = {"game": game_id}
        if certif:
            params["certificate_id"] = certif["id"]
            params["certificate_hash"] = CryptoHelper.generateHashFromCertif(certif)
        response = self.zaap_session.get(url, params=params, verify=False)
        response.raise_for_status()
        body = response.json()
        return body["token"]
