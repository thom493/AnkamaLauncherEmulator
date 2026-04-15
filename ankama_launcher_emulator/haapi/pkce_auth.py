"""
OAuth 2.0 PKCE authentication flow for Ankama accounts.

When a proxy IP triggers Ankama Shield, this module handles re-authentication
by running the PKCE flow through the proxy. The user completes login + Shield
verification in their system browser, then pastes back the authorization code.

Flow:
  1. Generate code_verifier + code_challenge
  2. Build auth URL (auth.ankama.com)
  3. User opens URL in browser (routed through proxy)
  4. User logs in, handles Shield if prompted
  5. Browser redirects to zaap://login?code=XXX
  6. User copies code, pastes into emulator dialog
  7. Exchange code for access_token (API key) via auth.ankama.com/token
"""

import hashlib
import base64
import logging
import random

import requests

from ankama_launcher_emulator.haapi.zaap_version import ZAAP_VERSION
from ankama_launcher_emulator.utils.proxy import to_socks5h

logger = logging.getLogger()

AUTH_BASE = "https://auth.ankama.com"
REDIRECT_URI = "zaap://login"
CHARSET = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-._~"


def generate_code_verifier() -> str:
    """Generate PKCE code_verifier (43-128 chars, RFC 7636)."""
    length = int(85 * random.random() + 43)
    return "".join(CHARSET[int(random.random() * len(CHARSET))] for _ in range(length))


def create_code_challenge(verifier: str) -> str:
    """SHA256 hash of verifier, base64url-encoded without padding."""
    digest = hashlib.sha256(verifier.encode()).digest()
    return base64.urlsafe_b64encode(digest).decode("utf-8").rstrip("=")


def build_auth_url(code_challenge: str, game_id: int = 102) -> str:
    """Build the auth URL the user opens in their browser."""
    return (
        f"{AUTH_BASE}/login/ankama"
        f"?code_challenge={code_challenge}"
        f"&redirect_uri={REDIRECT_URI}"
        f"&client_id={game_id}"
        f"&direct=true"
        f"&origin_tracker=https://www.ankama-launcher.com/launcher"
    )


def exchange_code_for_token(
    code: str,
    code_verifier: str,
    game_id: int = 102,
    proxy_url: str | None = None,
) -> str:
    """Exchange authorization code for access_token (API key).

    Returns the access_token string.
    Raises on failure.
    """
    session = requests.Session()
    if proxy_url:
        h_url = to_socks5h(proxy_url)
        session.proxies = {"http": h_url, "https": h_url}

    payload = (
        f"grant_type=authorization_code"
        f"&code={code}"
        f"&redirect_uri={REDIRECT_URI}"
        f"&client_id={game_id}"
        f"&code_verifier={code_verifier}"
    )

    response = session.post(
        f"{AUTH_BASE}/token",
        headers={
            "User-Agent": f"Zaap {ZAAP_VERSION}",
            "Content-Type": "application/x-www-form-urlencoded",
        },
        data=payload,
        verify=False,
    )
    response.raise_for_status()
    body = response.json()
    access_token = body["access_token"]
    logger.info("[PKCE] Token exchange successful")
    return access_token


class PkceSession:
    """Holds state for one PKCE auth attempt."""

    def __init__(self, game_id: int = 102, proxy_url: str | None = None):
        self.game_id = game_id
        self.proxy_url = proxy_url
        self.code_verifier = generate_code_verifier()
        self.code_challenge = create_code_challenge(self.code_verifier)
        self.auth_url = build_auth_url(self.code_challenge, game_id)

    def exchange(self, code: str) -> str:
        """Exchange the code the user pasted for an access_token."""
        return exchange_code_for_token(
            code=code,
            code_verifier=self.code_verifier,
            game_id=self.game_id,
            proxy_url=self.proxy_url,
        )
