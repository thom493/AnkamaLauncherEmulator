"""OAuth 2.0 PKCE authentication flow for Ankama accounts.

Two modes:
  A) Browser-based (PkceSession): local HTTP server on port 9001
  B) Programmatic (programmatic_pkce_login): headless, login+password, no browser
"""

import hashlib
import base64
import logging
import random
import re
import webbrowser
from http.server import HTTPServer, BaseHTTPRequestHandler
from typing import Callable
from urllib.parse import urlparse, parse_qs, urlencode

import requests

from ankama_launcher_emulator.haapi.zaap_version import ZAAP_VERSION
from ankama_launcher_emulator.utils.proxy import to_socks5h


logger = logging.getLogger()

AUTH_BASE = "https://auth.ankama.com"
LOCAL_REDIRECT_URI = "http://127.0.0.1:9001/authorized"
ZAAP_CLIENT_ID = 102  # Always 102 for PKCE auth (launcher ID, not game ID)
CHARSET = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-._~"


def generate_code_verifier() -> str:
    """Generate PKCE code_verifier (43-128 chars, RFC 7636)."""
    length = int(85 * random.random() + 43)
    return "".join(CHARSET[int(random.random() * len(CHARSET))] for _ in range(length))


def create_code_challenge(verifier: str) -> str:
    """SHA256 hash of verifier, base64url-encoded without padding."""
    digest = hashlib.sha256(verifier.encode()).digest()
    return base64.urlsafe_b64encode(digest).decode("utf-8").rstrip("=")


def build_auth_url(code_challenge: str) -> str:
    """Build the auth URL the user opens in their browser."""
    return (
        f"{AUTH_BASE}/login/ankama"
        f"?code_challenge={code_challenge}"
        f"&redirect_uri={LOCAL_REDIRECT_URI}"
        f"&client_id={ZAAP_CLIENT_ID}"
        f"&direct=true"
        f"&origin_tracker=https://www.ankama-launcher.com/launcher"
    )


def exchange_code_for_token(
    code: str,
    code_verifier: str,
) -> dict:
    """Exchange authorization code for access_token + refresh_token.

    Token exchange always goes direct (no proxy) — auth.ankama.com
    blocks proxy IPs on the /token endpoint.
    """
    payload = (
        f"grant_type=authorization_code"
        f"&code={code}"
        f"&redirect_uri={LOCAL_REDIRECT_URI}"
        f"&client_id={ZAAP_CLIENT_ID}"
        f"&code_verifier={code_verifier}"
    )

    response = requests.post(
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
    logger.info("[PKCE] Token exchange successful")
    return {
        "access_token": body["access_token"],
        "refresh_token": body.get("refresh_token"),
    }


class _CallbackHandler(BaseHTTPRequestHandler):
    """Handles the redirect from auth.ankama.com after login."""

    auth_code: str | None = None

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        params = parse_qs(parsed.query)
        code = params.get("code", [None])[0]
        if code:
            _CallbackHandler.auth_code = code
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(
            b"<html><body><h2>Authentication complete</h2>"
            b"<p>You can close this window and return to the launcher.</p>"
            b"</body></html>"
        )

    def log_message(self, format: str, *args: object) -> None:
        pass  # Suppress HTTP server logs


class PkceSession:
    """Holds state for one PKCE auth attempt with local callback server."""

    def __init__(self, game_id: int = 102):
        self.game_id = game_id
        self.code_verifier = generate_code_verifier()
        self.code_challenge = create_code_challenge(self.code_verifier)
        self.auth_url = build_auth_url(self.code_challenge)
        self._server: HTTPServer | None = None

    def run_and_wait_for_code(self, timeout: float = 120) -> str | None:
        """Start local server, open browser, wait for auth code.

        Returns the authorization code or None on timeout.
        """
        _CallbackHandler.auth_code = None
        self._server = HTTPServer(("127.0.0.1", 9001), _CallbackHandler)
        self._server.timeout = timeout

        webbrowser.open(self.auth_url)
        logger.info("[PKCE] Browser opened, waiting for callback on :9001")

        # Handle one request (the redirect callback)
        self._server.handle_request()
        self._server.server_close()
        self._server = None

        code = _CallbackHandler.auth_code
        if code:
            logger.info("[PKCE] Auth code received")
        else:
            logger.warning("[PKCE] No auth code received (timeout or error)")
        return code

    def exchange(self, code: str) -> dict:
        """Exchange the authorization code for tokens."""
        return exchange_code_for_token(
            code=code,
            code_verifier=self.code_verifier,
        )


# --- Programmatic PKCE (no browser) ---

ZAAP_REDIRECT_URI = "zaap://login"

_FORM_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:124.0) Gecko/20100101 Firefox/124.0",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "fr,fr-FR;q=0.8,en-US;q=0.5,en;q=0.3",
    "Content-Type": "application/x-www-form-urlencoded",
    "Upgrade-Insecure-Requests": "1",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "same-origin",
    "Sec-Fetch-User": "?1",
    "Pragma": "no-cache",
    "Cache-Control": "no-cache",
}

HAAPI_ACCOUNT_URL = "https://haapi.ankama.com/json/Ankama/v5/Account/Account"


def programmatic_pkce_login(
    login: str,
    password: str,
    proxy_url: str | None = None,
    on_progress: Callable | None = None,
) -> dict:
    """Full PKCE login without browser. Returns account data dict.

    Flow (matching dofus-multi put-account):
    1. GET /login/ankama?code_challenge=...&redirect_uri=zaap://login&client_id=102
    2. Follow redirect, extract CSRF state from HTML
    3. POST /login/ankama/form with login, password, state
    4. Follow redirect chain, extract auth code from body/location
    5. POST /token to exchange code for tokens (direct, no proxy)
    6. GET /Account/Account for account info

    Returns: {access_token, refresh_token, account_id, login, nickname, security}
    """

    def progress(msg: str) -> None:
        if on_progress:
            on_progress(msg)

    code_verifier = generate_code_verifier()
    code_challenge = create_code_challenge(code_verifier)

    session = requests.Session()
    if proxy_url:
        h_url = to_socks5h(proxy_url)
        session.proxies = {"http": h_url, "https": h_url}

    # Step 1: GET auth page
    progress("Starting authentication...")
    auth_url = (
        f"{AUTH_BASE}/login/ankama"
        f"?code_challenge={code_challenge}"
        f"&redirect_uri={ZAAP_REDIRECT_URI}"
        f"&client_id={ZAAP_CLIENT_ID}"
        f"&direct=true"
        f"&origin_tracker=https://www.ankama-launcher.com/launcher"
    )
    resp = session.get(
        auth_url, headers=_FORM_HEADERS, allow_redirects=True, verify=False
    )
    location = resp.headers.get("location")

    # If we got a redirect, follow it
    if location:
        resp = session.get(
            f"{AUTH_BASE}{location}" if location.startswith("/") else location,
            headers=_FORM_HEADERS,
            allow_redirects=True,
            verify=False,
        )

    # Step 2: Extract CSRF state from HTML form
    html = resp.text
    state_match = re.search(r'name="state"\s+value="([^"]+)"', html)
    if not state_match:
        raise RuntimeError("Failed to extract CSRF state from login page")
    state = state_match.group(1)
    logger.info("[PKCE-PROG] Got CSRF state")

    # Step 3: POST credentials
    progress("Submitting credentials...")
    resp = session.post(
        f"{AUTH_BASE}/login/ankama/form",
        headers=_FORM_HEADERS,
        data=urlencode({"login": login, "password": password, "state": state}),
        allow_redirects=False,
        verify=False,
    )

    location = resp.headers.get("location")
    if not location:
        raise RuntimeError("Incorrect login or password")

    # Step 4: Follow redirect to get auth code
    # The redirect may contain the code directly or need one more hop
    resp = session.get(
        f"{AUTH_BASE}{location}" if location.startswith("/") else location,
        headers=_FORM_HEADERS,
        allow_redirects=False,
        verify=False,
    )

    # Extract code from response body or location header
    code = None
    body_text = resp.text if resp.text else ""
    loc2 = resp.headers.get("location", "")

    # Try body first (zaap://login?code=XXX in href)
    code_match = re.search(r'[?&]code=([^"&\s]+)', body_text)
    if code_match:
        code = code_match.group(1)
    # Try location header
    if not code:
        code_match = re.search(r"[?&]code=([^&\s]+)", loc2)
        if code_match:
            code = code_match.group(1)

    if not code:
        raise RuntimeError("Failed to extract authorization code from redirect")

    logger.info("[PKCE-PROG] Got auth code")

    # Step 5: Exchange code for tokens (direct, no proxy — auth.ankama.com blocks proxies on /token)
    progress("Exchanging tokens...")
    token_payload = urlencode(
        {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": ZAAP_REDIRECT_URI,
            "client_id": ZAAP_CLIENT_ID,
            "code_verifier": code_verifier,
        }
    )
    token_resp = requests.post(
        f"{AUTH_BASE}/token",
        headers={
            "User-Agent": f"Zaap {ZAAP_VERSION}",
            "Content-Type": "application/x-www-form-urlencoded",
        },
        data=token_payload,
        verify=False,
    )
    token_resp.raise_for_status()
    tokens = token_resp.json()

    access_token = tokens["access_token"]
    refresh_token = tokens.get("refresh_token")
    logger.info("[PKCE-PROG] Token exchange successful")

    # Step 6: Get account info
    progress("Fetching account info...")
    acct_resp = session.get(
        HAAPI_ACCOUNT_URL,
        headers={"APIKEY": access_token},
        verify=False,
    )
    acct_resp.raise_for_status()
    account = acct_resp.json()

    if not account.get("id"):
        raise RuntimeError("Failed to get account info")

    return {
        "access_token": access_token,
        "refresh_token": refresh_token,
        "account_id": account["id"],
        "login": account.get("login", login),
        "nickname": account.get("nickname", ""),
        "security": account.get("security", []),
    }
