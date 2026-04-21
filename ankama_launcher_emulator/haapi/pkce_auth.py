"""OAuth 2.0 PKCE authentication flow for Ankama accounts.

Two modes:
  A) Browser-based (PkceSession): local HTTP server on port 9001
  B) Programmatic (programmatic_pkce_login): headless, login+password, no browser
"""

import asyncio
import hashlib
import base64
import logging
import random
import re
import webbrowser
from http.server import HTTPServer, BaseHTTPRequestHandler
from typing import Any, Callable
from urllib.parse import urlparse, parse_qs, urlencode

import requests
from rnet import Client as _RClient, Cookie as _RCookie, Impersonate as _RImp, Proxy as _RProxy

from ankama_launcher_emulator.haapi.zaap_version import ZAAP_VERSION
from ankama_launcher_emulator.utils.proxy import to_socks5h


logger = logging.getLogger()

AUTH_BASE = "https://auth.ankama.com"
LOCAL_REDIRECT_URI = "http://127.0.0.1:9001/authorized"
ZAAP_CLIENT_ID = 102  # Launcher PKCE client
CHARSET = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-._~"


def generate_code_verifier() -> str:
    """Generate PKCE code_verifier (43-128 chars, RFC 7636)."""
    length = int(85 * random.random() + 43)
    return "".join(CHARSET[int(random.random() * len(CHARSET))] for _ in range(length))


def create_code_challenge(verifier: str) -> str:
    """SHA256 hash of verifier, base64url-encoded without padding."""
    digest = hashlib.sha256(verifier.encode()).digest()
    return base64.urlsafe_b64encode(digest).decode("utf-8").rstrip("=")


def build_auth_url(
    code_challenge: str,
    redirect_uri: str = LOCAL_REDIRECT_URI,
) -> str:
    """Build the auth URL the user opens in their browser."""
    return (
        f"{AUTH_BASE}/login/ankama"
        f"?code_challenge={code_challenge}"
        f"&redirect_uri={redirect_uri}"
        f"&client_id={ZAAP_CLIENT_ID}"
        f"&direct=true"
        f"&origin_tracker=https://www.ankama-launcher.com/launcher"
    )


def exchange_code_for_token(
    code: str,
    code_verifier: str,
    redirect_uri: str = LOCAL_REDIRECT_URI,
    cookies: dict[str, str] | None = None,
) -> dict:
    """Exchange authorization code for access_token + refresh_token.

    Token exchange always goes direct (no proxy) — auth.ankama.com
    blocks proxy IPs on the /token endpoint.

    cookies: pass browser cookies (e.g. aws-waf-token) captured during
    the embedded login so AWS WAF does not 403 the token call.
    """
    payload = (
        f"grant_type=authorization_code"
        f"&code={code}"
        f"&redirect_uri={redirect_uri}"
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
        cookies=cookies or None,
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


class ZaapPkceSession:
    """PKCE session that completes via zaap://login in an embedded browser."""

    def __init__(self):
        self.code_verifier = generate_code_verifier()
        self.code_challenge = create_code_challenge(self.code_verifier)
        self.auth_url = build_auth_url(
            self.code_challenge,
            redirect_uri=ZAAP_REDIRECT_URI,
        )

    def exchange(self, code: str, cookies: dict[str, str] | None = None) -> dict:
        return exchange_code_for_token(
            code=code,
            code_verifier=self.code_verifier,
            redirect_uri=ZAAP_REDIRECT_URI,
            cookies=cookies,
        )


def complete_embedded_login(
    code: str,
    session: ZaapPkceSession,
    login: str,
    cookies: dict[str, str] | None = None,
) -> dict:
    tokens = session.exchange(code, cookies=cookies)
    account = fetch_account_profile(tokens["access_token"])
    if not account.get("id"):
        raise RuntimeError("Failed to get account info")
    return {
        "access_token": tokens["access_token"],
        "refresh_token": tokens.get("refresh_token"),
        "account_id": account["id"],
        "login": account.get("login", login),
        "nickname": account.get("nickname", ""),
        "security": account.get("security", []),
    }

HAAPI_ACCOUNT_URL = "https://haapi.ankama.com/json/Ankama/v5/Account/Account"


def fetch_account_profile(access_token: str, proxy_url: str | None = None) -> dict:
    session = requests.Session()
    if proxy_url:
        h_url = to_socks5h(proxy_url)
        session.proxies = {"http": h_url, "https": h_url}

    acct_resp = session.get(
        HAAPI_ACCOUNT_URL,
        headers={"APIKEY": access_token},
        verify=False,
    )
    acct_resp.raise_for_status()
    return acct_resp.json()


_CHROME_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/137.0.0.0 Safari/537.36"
)


def _chrome_nav_headers() -> dict:
    return {
        "accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7",
        "accept-language": "en-US,en;q=0.9",
        "sec-ch-ua": '"Chromium";v="137", "Google Chrome";v="137", "Not=A?Brand";v="24"',
        "sec-ch-ua-mobile": "?0",
        "sec-ch-ua-platform": '"Windows"',
        "sec-fetch-dest": "document",
        "sec-fetch-mode": "navigate",
        "sec-fetch-site": "none",
        "sec-fetch-user": "?1",
        "upgrade-insecure-requests": "1",
        "user-agent": _CHROME_UA,
    }


def _h(val: Any) -> str:
    if val is None:
        return ""
    if isinstance(val, (bytes, bytearray)):
        return val.decode(errors="replace")
    return str(val)


def _make_rnet_client(proxy_url: str | None) -> _RClient:
    opts: dict[str, Any] = {"impersonate": _RImp.Chrome137, "cookie_store": True}
    if proxy_url:
        opts["proxies"] = [_RProxy.all(to_socks5h(proxy_url))]
    return _RClient(**opts)


def _inject_waf_cookie(client: _RClient, waf_token: str) -> None:
    client.set_cookie(
        "https://auth.ankama.com/",
        _RCookie(name="aws-waf-token", value=waf_token,
                 domain="auth.ankama.com", path="/"),
    )


async def _async_pkce_login(
    login: str,
    password: str,
    proxy_url: str | None,
    progress: Callable[[str], None],
) -> dict:
    """PKCE login via rnet (Chrome137 TLS impersonation).

    AWS WAF JA3/JA4 fingerprints the TLS ClientHello. PyInstaller-Windows
    Python's OpenSSL produces a bot-like signature and gets hard-blocked
    at the CloudFront edge (403), so the entire auth.ankama.com flow
    must share the same Chrome fingerprint that the WAF solver uses.
    """
    from ankama_launcher_emulator.haapi.aws_waf_bypass import _get_token_async

    code_verifier = generate_code_verifier()
    code_challenge = create_code_challenge(code_verifier)

    client = _make_rnet_client(proxy_url)

    # Step 0: solve WAF, inject token cookie into our client's store.
    progress("Solving AWS WAF challenge...")
    logger.info("[PKCE-PROG] step0 solving WAF")
    waf_token = await _get_token_async("", proxy_url)
    _inject_waf_cookie(client, waf_token)
    logger.info(
        "[PKCE-PROG] step0 WAF cookie injected (len=%d, head=%r)",
        len(waf_token or ""), (waf_token or "")[:16],
    )

    # Step 1: GET /login/ankama (auto-follows to /login/ankama/form)
    progress("Starting authentication...")
    auth_url = (
        f"{AUTH_BASE}/login/ankama"
        f"?code_challenge={code_challenge}"
        f"&redirect_uri={ZAAP_REDIRECT_URI}"
        f"&client_id={ZAAP_CLIENT_ID}"
        f"&direct=true"
        f"&origin_tracker=https://www.ankama-launcher.com/launcher"
    )
    resp = await client.get(
        auth_url, headers=_chrome_nav_headers(), allow_redirects=True,
    )
    html = await resp.text()
    final_url = _h(resp.url) or auth_url
    logger.info(
        "[PKCE-PROG] step1 GET /login/ankama status=%s len=%d final_url=%s",
        resp.status_code, len(html or ""), final_url[:200],
    )

    # Step 2: Extract CSRF state
    state_match = re.search(r'name="state"\s+value="([^"]+)"', html)
    if not state_match:
        logger.error(
            "[PKCE-PROG] CSRF state missing — status=%s url=%s html_head=%r",
            resp.status_code, final_url, (html[:500] if html else ""),
        )
        raise RuntimeError("Failed to extract CSRF state from login page")
    state = state_match.group(1)
    logger.info("[PKCE-PROG] step2 CSRF state extracted (len=%d)", len(state))

    # Step 3: POST credentials
    progress("Submitting credentials...")
    form_headers = {
        **_chrome_nav_headers(),
        "content-type": "application/x-www-form-urlencoded",
        "origin": AUTH_BASE,
        "referer": final_url,
        "sec-fetch-site": "same-origin",
    }
    resp_post = await client.post(
        f"{AUTH_BASE}/login/ankama/form",
        body=urlencode({"login": login, "password": password, "state": state}),
        headers=form_headers,
        allow_redirects=False,
    )
    location = _h(resp_post.headers.get("location"))
    logger.info(
        "[PKCE-PROG] step3 POST /login/ankama/form status=%s has_location=%s",
        resp_post.status_code, bool(location),
    )
    if not location:
        body_post = await resp_post.text()
        logger.error(
            "[PKCE-PROG] no redirect — status=%s body_head=%r",
            resp_post.status_code, (body_post or "")[:300],
        )
        raise RuntimeError("Incorrect login or password")

    # Step 4: Follow redirect — one hop, look for auth code in body + location
    redirect_url = f"{AUTH_BASE}{location}" if location.startswith("/") else location
    logger.info("[PKCE-PROG] step4 following redirect to=%s", redirect_url[:120])
    resp4 = await client.get(
        redirect_url, headers=_chrome_nav_headers(), allow_redirects=False,
    )
    body_text = await resp4.text()
    loc2 = _h(resp4.headers.get("location"))
    logger.info(
        "[PKCE-PROG] step4 status=%s has_location=%s body_len=%d",
        resp4.status_code, bool(loc2), len(body_text or ""),
    )

    code = None
    m = re.search(r'[?&]code=([^"&\s]+)', body_text or "")
    if m:
        code = m.group(1)
    if not code and loc2:
        m = re.search(r"[?&]code=([^&\s]+)", loc2)
        if m:
            code = m.group(1)
    if not code:
        logger.error(
            "[PKCE-PROG] no auth code — body_head=%r loc2=%r",
            (body_text or "")[:300], loc2[:300],
        )
        raise RuntimeError("Failed to extract authorization code from redirect")
    logger.info("[PKCE-PROG] step4 got auth code (len=%d)", len(code))

    # Step 5: /token exchange — direct (no proxy), Chrome137 TLS, WAF cookie
    progress("Exchanging tokens...")
    direct_client = _RClient(impersonate=_RImp.Chrome137, cookie_store=True)
    _inject_waf_cookie(direct_client, waf_token)
    token_payload = urlencode({
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": ZAAP_REDIRECT_URI,
        "client_id": ZAAP_CLIENT_ID,
        "code_verifier": code_verifier,
    })
    token_resp = await direct_client.post(
        f"{AUTH_BASE}/token",
        body=token_payload,
        headers={
            "user-agent": f"Zaap {ZAAP_VERSION}",
            "content-type": "application/x-www-form-urlencoded",
        },
    )
    tokens = await token_resp.json()
    if not isinstance(tokens, dict) or "access_token" not in tokens:
        logger.error("[PKCE-PROG] token exchange failed: status=%s body=%r",
                     token_resp.status_code, tokens)
        raise RuntimeError(f"Token exchange failed (status {token_resp.status_code})")
    access_token = tokens["access_token"]
    refresh_token = tokens.get("refresh_token")
    logger.info("[PKCE-PROG] step5 token exchange successful")

    # Step 6: /Account/Account — haapi host, not WAF-gated, keep requests
    progress("Fetching account info...")
    account = fetch_account_profile(access_token, proxy_url=proxy_url)
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


def programmatic_pkce_login(
    login: str,
    password: str,
    proxy_url: str | None = None,
    on_progress: Callable | None = None,
) -> dict:
    """Full PKCE login without browser. Returns account data dict.

    Runs the async rnet-based flow. Safe to call from any thread that
    does not already own an event loop (re-runs on a worker thread if so).
    """

    def progress(msg: str) -> None:
        if on_progress:
            on_progress(msg)

    try:
        return asyncio.run(_async_pkce_login(login, password, proxy_url, progress))
    except RuntimeError as exc:
        if "event loop" not in str(exc).lower():
            raise
        import threading

        result: dict[str, Any] = {}

        def runner() -> None:
            try:
                result["ok"] = asyncio.run(
                    _async_pkce_login(login, password, proxy_url, progress)
                )
            except Exception as inner:
                result["err"] = inner

        t = threading.Thread(target=runner, daemon=True)
        t.start()
        t.join()
        if "err" in result:
            raise result["err"]
        return result["ok"]


