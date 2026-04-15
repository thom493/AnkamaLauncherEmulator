"""OAuth 2.0 PKCE authentication flow for Ankama accounts.

Matches the official Zaap launcher flow:
  1. Start local HTTP server on port 9001
  2. Generate code_verifier + code_challenge
  3. Open auth URL in system browser with redirect_uri=http://127.0.0.1:9001/authorized
  4. User logs in, browser redirects to local server with ?code=XXX
  5. Server captures code automatically
  6. Exchange code for access_token + refresh_token via auth.ankama.com/token
"""

import hashlib
import base64
import logging
import random
import threading
import webbrowser
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs

import requests

from ankama_launcher_emulator.haapi.zaap_version import ZAAP_VERSION
from ankama_launcher_emulator.utils.proxy import to_socks5h

logger = logging.getLogger()

AUTH_BASE = "https://auth.ankama.com"
LOCAL_REDIRECT_URI = "http://127.0.0.1:9001/authorized"
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
        f"&redirect_uri={LOCAL_REDIRECT_URI}"
        f"&client_id={game_id}"
        f"&direct=true"
        f"&origin_tracker=https://www.ankama-launcher.com/launcher"
    )


def exchange_code_for_token(
    code: str,
    code_verifier: str,
    game_id: int = 102,
    proxy_url: str | None = None,
) -> dict:
    """Exchange authorization code for access_token + refresh_token.

    Returns dict with 'access_token' and 'refresh_token'.
    Raises on failure.
    """
    session = requests.Session()
    if proxy_url:
        h_url = to_socks5h(proxy_url)
        session.proxies = {"http": h_url, "https": h_url}

    payload = (
        f"grant_type=authorization_code"
        f"&code={code}"
        f"&redirect_uri={LOCAL_REDIRECT_URI}"
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

    def __init__(self, game_id: int = 102, proxy_url: str | None = None):
        self.game_id = game_id
        self.proxy_url = proxy_url
        self.code_verifier = generate_code_verifier()
        self.code_challenge = create_code_challenge(self.code_verifier)
        self.auth_url = build_auth_url(self.code_challenge, game_id)
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
            game_id=self.game_id,
            proxy_url=self.proxy_url,
        )
