"""Interactive debug harness for the Ankama add-account login sequence.

Two modes:
  headless  - run programmatic_pkce_login end-to-end, log every HTTP call
  browser   - open the embedded Chromium dialog, log JS console + nav events

Credentials come from tests/.env (see tests/.env.example).

Usage:
    python tests/debug_login.py --mode headless
    python tests/debug_login.py --mode browser
    python tests/debug_login.py --mode headless --no-waf
    python tests/debug_login.py --mode headless --reuse-session
"""

from __future__ import annotations

import argparse
import os
import sys
import traceback
import urllib3
from pathlib import Path

# Ensure project root on sys.path when invoked as `python tests/debug_login.py`
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

# Suppress requests SSL warnings (we use verify=False for everything)
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

from tests import _debug_session as dbg


def _get_credentials(args: argparse.Namespace) -> tuple[str, str]:
    dbg.load_dotenv()
    login = args.login or os.environ.get("ANKAMA_TEST_LOGIN")
    password = args.password or os.environ.get("ANKAMA_TEST_PASSWORD")
    if not login:
        login = input("Login (email): ").strip()
    if not password:
        import getpass
        password = getpass.getpass("Password: ")
    return login, password


# ──────────────────────────────────────────────────────────────────────────────
# Headless mode
# ──────────────────────────────────────────────────────────────────────────────


def run_headless(args: argparse.Namespace) -> int:
    login, password = _get_credentials(args)
    dbg.install_global_hook()

    dbg.banner(f"HEADLESS PKCE LOGIN — {login}")
    dbg.info(f"WAF bypass: {'DISABLED (--no-waf)' if args.no_waf else 'enabled'}")
    dbg.info(f"Token session: {'reuse auth session (--reuse-session)' if args.reuse_session else 'fresh session'}")

    if args.no_waf or args.reuse_session:
        return _run_custom_headless(login, password, no_waf=args.no_waf, reuse_session=args.reuse_session)

    # Default: run the production code path verbatim
    from ankama_launcher_emulator.haapi.pkce_auth import programmatic_pkce_login

    try:
        result = programmatic_pkce_login(
            login,
            password,
            on_progress=lambda m: dbg.info(f"[progress] {m}"),
        )
    except Exception as exc:
        dbg.fail(f"login failed: {exc}")
        traceback.print_exc()
        return 1

    dbg.banner("RESULT")
    for k, v in result.items():
        if k in {"access_token", "refresh_token"}:
            v = (v or "")[:24] + "…"
        dbg.ok(f"{k}: {v}")
    return 0


def _run_custom_headless(login: str, password: str, *, no_waf: bool, reuse_session: bool) -> int:
    """Reimplements the steps inline so we can flip flags without touching prod."""
    import re
    from urllib.parse import urlencode
    import requests

    from ankama_launcher_emulator.haapi.pkce_auth import (
        AUTH_BASE,
        ZAAP_CLIENT_ID,
        ZAAP_REDIRECT_URI,
        _FORM_HEADERS,
        create_code_challenge,
        fetch_account_profile,
        generate_code_verifier,
    )
    from ankama_launcher_emulator.haapi.zaap_version import ZAAP_VERSION

    code_verifier = generate_code_verifier()
    code_challenge = create_code_challenge(code_verifier)

    session = requests.Session()

    dbg.step(1, 6, "GET auth page")
    auth_url = (
        f"{AUTH_BASE}/login/ankama"
        f"?code_challenge={code_challenge}"
        f"&redirect_uri={ZAAP_REDIRECT_URI}"
        f"&client_id={ZAAP_CLIENT_ID}"
        f"&direct=true"
        f"&origin_tracker=https://www.ankama-launcher.com/launcher"
    )
    resp = session.get(auth_url, headers=_FORM_HEADERS, allow_redirects=True, verify=False)
    html = resp.text

    dbg.step(2, 6, "Extract CSRF state")
    state_match = re.search(r'name="state"\s+value="([^"]+)"', html)
    if not state_match:
        dbg.fail("could not extract CSRF state from login page")
        return 1
    state = state_match.group(1)
    dbg.ok(f"state = {state[:32]}…")

    waf_token = None
    if not no_waf:
        dbg.step(3, 6, "AWS WAF bypass")
        from ankama_launcher_emulator.haapi.aws_waf_bypass import get_aws_waf_token
        waf_token = get_aws_waf_token(state)
        session.cookies.set("aws-waf-token", waf_token, domain="auth.ankama.com", path="/")
        dbg.ok(f"waf token = {waf_token[:24]}…")
    else:
        dbg.step(3, 6, "AWS WAF bypass — SKIPPED")

    dbg.step(4, 6, "POST credentials")
    resp = session.post(
        f"{AUTH_BASE}/login/ankama/form",
        headers=_FORM_HEADERS,
        data=urlencode({"login": login, "password": password, "state": state}),
        allow_redirects=False,
        verify=False,
    )
    location = resp.headers.get("location")
    if not location:
        dbg.fail("no Location header on credentials POST — wrong password or WAF block")
        return 1
    dbg.ok(f"got Location → {location[:120]}")

    resp = session.get(
        f"{AUTH_BASE}{location}" if location.startswith("/") else location,
        headers=_FORM_HEADERS,
        allow_redirects=False,
        verify=False,
    )

    code = None
    body_text = resp.text or ""
    loc2 = resp.headers.get("location", "")
    m = re.search(r'[?&]code=([^"&\s]+)', body_text)
    if m:
        code = m.group(1)
    if not code:
        m = re.search(r"[?&]code=([^&\s]+)", loc2)
        if m:
            code = m.group(1)
    if not code:
        dbg.fail("no auth code in response body or location header")
        return 1
    dbg.ok(f"auth code = {code[:32]}…")

    dbg.step(5, 6, f"POST /token  ({'reuse auth session' if reuse_session else 'fresh session'})")
    if reuse_session:
        token_session = session
    else:
        token_session = requests.Session()
        if waf_token:
            token_session.cookies.set("aws-waf-token", waf_token, domain="auth.ankama.com", path="/")

    token_resp = token_session.post(
        f"{AUTH_BASE}/token",
        headers={
            "User-Agent": f"Zaap {ZAAP_VERSION}",
            "Content-Type": "application/x-www-form-urlencoded",
        },
        data=urlencode({
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": ZAAP_REDIRECT_URI,
            "client_id": ZAAP_CLIENT_ID,
            "code_verifier": code_verifier,
        }),
        verify=False,
    )
    if not token_resp.ok:
        dbg.fail(f"token exchange failed: HTTP {token_resp.status_code}")
        return 1
    tokens = token_resp.json()
    if "access_token" not in tokens:
        dbg.fail(f"no access_token in response: {token_resp.text[:200]}")
        return 1
    dbg.ok(f"access_token = {tokens['access_token'][:24]}…")

    dbg.step(6, 6, "GET /Account/Account")
    account = fetch_account_profile(tokens["access_token"])
    dbg.ok(f"account_id={account.get('id')}  login={account.get('login')}  security={account.get('security')}")
    return 0


# ──────────────────────────────────────────────────────────────────────────────
# Browser mode
# ──────────────────────────────────────────────────────────────────────────────


def run_browser(args: argparse.Namespace) -> int:
    login, _password = _get_credentials(args)
    dbg.install_global_hook()

    # Force AA_ShareOpenGLContexts before QApplication
    from PyQt6.QtCore import Qt, QCoreApplication
    QCoreApplication.setAttribute(Qt.ApplicationAttribute.AA_ShareOpenGLContexts, True)

    from PyQt6.QtCore import QUrl, pyqtSignal
    from PyQt6.QtWebEngineCore import (
        QWebEnginePage,
        QWebEngineProfile,
        QWebEngineUrlScheme,
    )
    from PyQt6.QtWebEngineWidgets import QWebEngineView
    from PyQt6.QtWidgets import QApplication, QDialog, QVBoxLayout
    from qfluentwidgets import BodyLabel

    # Register custom scheme BEFORE QApplication — otherwise Chromium
    # silently drops navigations to it instead of routing through
    # acceptNavigationRequest. (Confirmed: zaap:// dispatches without
    # registration but qt-token-result:// does not in this Qt build.)
    if not QApplication.instance():
        scheme = QWebEngineUrlScheme(b"qt-token-result")
        scheme.setSyntax(QWebEngineUrlScheme.Syntax.Path)
        scheme.setFlags(
            QWebEngineUrlScheme.Flag.SecureScheme
            | QWebEngineUrlScheme.Flag.LocalAccessAllowed
            | QWebEngineUrlScheme.Flag.CorsEnabled
        )
        QWebEngineUrlScheme.registerScheme(scheme)
        dbg.info("registered qt-token-result:// scheme")

    from ankama_launcher_emulator.haapi.pkce_auth import (
        AUTH_BASE,
        ZAAP_CLIENT_ID,
        ZAAP_REDIRECT_URI,
        create_code_challenge,
        generate_code_verifier,
        fetch_account_profile,
    )

    app = QApplication.instance() or QApplication(sys.argv)

    code_verifier = generate_code_verifier()
    code_challenge = create_code_challenge(code_verifier)
    auth_url = (
        f"{AUTH_BASE}/login/ankama"
        f"?code_challenge={code_challenge}"
        f"&redirect_uri={ZAAP_REDIRECT_URI}"
        f"&client_id={ZAAP_CLIENT_ID}"
        f"&direct=true"
        f"&origin_tracker=https://www.ankama-launcher.com/launcher"
    )

    dbg.banner(f"BROWSER PKCE LOGIN — {login}")
    dbg.info(f"auth_url = {auth_url[:140]}…")
    dbg.info("Enter credentials in the embedded browser window. Console + nav events stream below.")

    class VerbosePage(QWebEnginePage):
        code_received = pyqtSignal(str)
        token_exchange_done = pyqtSignal(int, str)

        def __init__(self, *a, **kw):
            super().__init__(*a, **kw)
            self._seen_code: str | None = None
            self.titleChanged.connect(self._on_title)

        def javaScriptConsoleMessage(self, level, message, line, source):
            level_map = {0: "LOG", 1: "WARN", 2: "ERR"}
            try:
                lvl_int = int(level.value) if hasattr(level, "value") else int(level)
            except Exception:
                lvl_int = -1
            tag = level_map.get(lvl_int, str(level))
            color = {"LOG": dbg._DIM, "WARN": dbg._YLW, "ERR": dbg._RED}.get(tag, dbg._DIM)
            print(f"  {color}[js {tag}] {source}:{line} — {message}{dbg._END}")

        def acceptNavigationRequest(self, url, navigation_type, is_main_frame):
            scheme = url.scheme()
            print(f"  {dbg._BLU}[nav] {url.toString()[:140]}{dbg._END}")
            if scheme == "zaap" and url.host() == "login":
                from PyQt6.QtCore import QUrlQuery
                code = QUrlQuery(url).queryItemValue("code")
                if code and code != self._seen_code:
                    self._seen_code = code
                    dbg.ok(f"intercepted auth code (len={len(code)})")
                    self.code_received.emit(code)
                elif code:
                    dbg.info(f"duplicate zaap nav for same code — ignored")
                return False
            return True

        def _on_title(self, title: str) -> None:
            if not title.startswith("__TOKEN__:"):
                return
            payload = title[len("__TOKEN__:"):]
            try:
                sep = payload.index(":")
                status = int(payload[:sep])
            except (ValueError, IndexError):
                dbg.fail(f"bad token title: {title[:100]}")
                return
            from urllib.parse import unquote
            body = unquote(payload[sep + 1:])
            self.token_exchange_done.emit(status, body)

    class HarnessDialog(QDialog):
        def __init__(self):
            super().__init__()
            self.setWindowTitle("Debug login — embedded browser")
            self.resize(900, 800)
            self.tokens: dict | None = None

            layout = QVBoxLayout(self)
            layout.addWidget(BodyLabel(f"Sign in as {login} below."))
            self.profile = QWebEngineProfile(self)
            self.profile.cookieStore().cookieAdded.connect(self._on_cookie)
            self.page = VerbosePage(self.profile, self)
            self.page.code_received.connect(self._on_code)
            self.page.token_exchange_done.connect(self._on_token)
            self.view = QWebEngineView(self)
            self.view.setPage(self.page)
            layout.addWidget(self.view, 1)
            self.view.setUrl(QUrl(auth_url))

        def _on_cookie(self, c):
            def _decode(field):
                if isinstance(field, (bytes, bytearray)):
                    return bytes(field).decode("ascii", errors="ignore")
                return str(field)
            domain = _decode(c.domain())
            if "ankama" not in domain.lower():
                return
            name = _decode(c.name())
            value = _decode(c.value())
            v_disp = value[:40] + "…" if len(value) > 40 else value
            path = ""
            if hasattr(c, "path"):
                try:
                    path = _decode(c.path())
                except Exception:
                    path = ""
            print(f"  {dbg._DIM}[cookie+] {domain}{path}  {name}={v_disp}{dbg._END}")

        def _on_code(self, code: str):
            from PyQt6.QtCore import QTimer
            dbg.info("scheduling JS /token fetch (deferred via QTimer)…")
            QTimer.singleShot(0, lambda: self._exchange(code))

        def _exchange(self, code: str):
            from urllib.parse import quote
            payload = (
                f"grant_type=authorization_code"
                f"&code={quote(code, safe='')}"
                f"&redirect_uri={quote(ZAAP_REDIRECT_URI, safe='')}"
                f"&client_id={ZAAP_CLIENT_ID}"
                f"&code_verifier={quote(code_verifier, safe='')}"
            )
            js = (
                "(function(){"
                "console.log('[harness] starting /token fetch');"
                f"fetch('{AUTH_BASE}/token',{{method:'POST',"
                "headers:{'Content-Type':'application/x-www-form-urlencoded'},"
                f"body:'{payload}'}})"
                ".then(function(r){console.log('[harness] /token status='+r.status);return r.text().then(function(t){return [r.status,t];});})"
                ".then(function(p){console.log('[harness] setting title with status='+p[0]+' body_len='+p[1].length);document.title='__TOKEN__:'+p[0]+':'+encodeURIComponent(p[1]);})"
                ".catch(function(e){console.log('[harness] fetch err: '+String(e));document.title='__TOKEN__:0:'+encodeURIComponent('err:'+String(e));});"
                "})();"
            )
            def _cb(result):
                dbg.info(f"runJavaScript callback fired (result={result!r})")
            try:
                self.page.runJavaScript(js, _cb)
            except Exception as exc:
                dbg.fail(f"runJavaScript raised: {exc}")

        def _on_token(self, status: int, body: str):
            import json
            print(f"  {dbg._BOLD}[token] HTTP {status}{dbg._END}")
            print(f"  {dbg._DIM}body: {body[:400]}{dbg._END}")
            if status == 200:
                try:
                    self.tokens = json.loads(body)
                    dbg.ok("token exchange OK")
                except Exception as exc:
                    dbg.fail(f"JSON parse error: {exc}")
            else:
                dbg.fail(f"token exchange failed: HTTP {status}")
            from PyQt6.QtCore import QTimer
            QTimer.singleShot(0, self.accept)

        def done(self, result: int) -> None:
            # Same teardown as production: page deleted before profile
            from PyQt6.QtCore import QTimer
            from PyQt6.QtWebEngineCore import QWebEnginePage as _Page
            if self.view is not None:
                dummy = _Page(self.view)
                self.view.setPage(dummy)
            if self.page is not None:
                page = self.page
                self.page = None
                page.setParent(None)
                if self.profile is not None:
                    profile = self.profile
                    self.profile = None
                    profile.setParent(None)
                    page.destroyed.connect(lambda: QTimer.singleShot(0, profile.deleteLater))
                page.deleteLater()
            super().done(result)

    dialog = HarnessDialog()
    rc = dialog.exec()
    if rc != QDialog.DialogCode.Accepted:
        dbg.fail("dialog cancelled")
        return 1

    if not dialog.tokens or "access_token" not in dialog.tokens:
        dbg.fail("no tokens captured")
        return 1

    dbg.banner("FETCHING ACCOUNT PROFILE")
    account = fetch_account_profile(dialog.tokens["access_token"])
    dbg.ok(f"account_id={account.get('id')} login={account.get('login')} security={account.get('security')}")

    # ── full chain: shield → signOn → createToken → game token ────────────────
    return _run_post_auth_chain(
        login=login,
        access_token=dialog.tokens["access_token"],
        refresh_token=dialog.tokens.get("refresh_token"),
        security=account.get("security", []),
        game_id=args.game,
    )


def _generate_fake_portable_profile(login: str) -> tuple[str, str, str]:
    """In-memory portable profile — mirrors AccountMeta.generate_fake_profile.

    Returns (fake_uuid, fake_hm1, fake_hm2). No disk writes; harness-only.
    Uses a deterministic seed from login so reruns reuse the same fake hardware.
    """
    import hashlib
    import uuid
    seed = hashlib.sha256(f"harness::{login}".encode("utf-8")).hexdigest()
    fake_uuid = str(uuid.UUID(seed[:32]))
    fake_machine_id = hashlib.sha256(fake_uuid.encode("utf-8")).hexdigest()
    machine_infos = ["x64", "win32", fake_machine_id, "user", "10", "16384"]
    fake_hm1 = hashlib.sha256("".join(machine_infos).encode("utf-8")).hexdigest()[:32]
    fake_hm2 = fake_hm1[::-1]
    dbg.info(f"fake portable profile: uuid={fake_uuid}  hm1={fake_hm1[:16]}…")
    return fake_uuid, fake_hm1, fake_hm2


def _run_post_auth_chain(
    login: str,
    access_token: str,
    refresh_token: str | None,
    security: list,
    game_id: int = 101,
) -> int:
    """Walk shield (if needed) → SignOnWithApiKey → CreateToken in-memory."""
    fake_uuid, fake_hm1, fake_hm2 = _generate_fake_portable_profile(login)

    cert: dict | None = None
    if "SHIELD" in security or "UNSECURED" in security:
        from ankama_launcher_emulator.haapi.shield import (
            request_security_code,
            validate_security_code,
        )

        dbg.banner("SHIELD ENROLLMENT")
        dbg.step(1, 3, "request_security_code (transportType=EMAIL)")
        try:
            request_security_code(access_token)
            dbg.ok("email sent — check inbox")
        except Exception as exc:
            dbg.fail(f"request_security_code failed: {exc}")
            return 1

        dbg.step(2, 3, "waiting for code from terminal")
        code = input("  enter Shield code from email: ").strip()
        if not code:
            dbg.fail("no code entered")
            return 1

        dbg.step(3, 3, "validate_security_code (with fake portable hm1/hm2)")
        try:
            cert = validate_security_code(access_token, code, hm1=fake_hm1, hm2=fake_hm2)
            dbg.ok(f"cert id={cert.get('id')} keys={list(cert.keys())}")
        except Exception as exc:
            dbg.fail(f"validate_security_code failed: {exc}")
            return 1
    else:
        dbg.info("no SHIELD on account — skipping shield enrollment")

    # ── SignOnWithApiKey + CreateToken via Haapi class ────────────────────────
    dbg.banner("SIGN ON + CREATE GAME TOKEN")
    import time as _time
    from ankama_launcher_emulator.haapi.haapi import Haapi
    import ankama_launcher_emulator.haapi.account_persistence as _ap

    # Token just minted via PKCE — skip refresh window so refreshApiKey is a no-op.
    # Also stub persist_token_refresh in case it fires (no disk writes from harness).
    _ap.persist_token_refresh = lambda *_a, **_kw: dbg.info("(harness) persist_token_refresh skipped")

    haapi = Haapi(
        api_key=access_token,
        login=login,
        interface_ip=None,
        proxy_url=None,
        refresh_token=refresh_token,
        refresh_date=int(_time.time() * 1000),
    )

    dbg.step(1, 2, "SignOnWithApiKey (game=102)")
    try:
        signon = haapi.signOnWithApiKey(102)
        dbg.ok(f"signOn keys={list(signon.keys())}")
    except Exception as exc:
        dbg.fail(f"signOnWithApiKey failed: {exc}")
        return 1

    dbg.step(2, 2, f"CreateToken (game={game_id}, with cert if any)")
    cert_payload = None
    if cert and "encodedCertificate" in cert:
        cert_payload = {
            "id": cert["id"],
            "encodedCertificate": cert["encodedCertificate"],
        }
    try:
        game_token = haapi.createToken(game_id, cert_payload, hm1=fake_hm1, hm2=fake_hm2)
        dbg.ok(f"GAME TOKEN (game={game_id}): {game_token}")
    except Exception as exc:
        dbg.fail(f"createToken failed: {exc}")
        return 1

    dbg.banner("FULL CHAIN OK")
    return 0


# ──────────────────────────────────────────────────────────────────────────────
# Entry
# ──────────────────────────────────────────────────────────────────────────────


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=["headless", "browser"], required=True)
    parser.add_argument("--login", help="Override ANKAMA_TEST_LOGIN")
    parser.add_argument("--password", help="Override ANKAMA_TEST_PASSWORD (avoid; use .env)")
    parser.add_argument("--no-waf", action="store_true", help="(headless) Skip AWS WAF bypass — test the dofus-multi path")
    parser.add_argument("--reuse-session", action="store_true", help="(headless) Use the auth session for /token — test the Bubble.D3 path")
    parser.add_argument("--game", type=int, default=101, help="Game id for CreateToken (101=Retro, 1=Dofus3, ...)")
    args = parser.parse_args()

    if args.mode == "headless":
        return run_headless(args)
    return run_browser(args)


if __name__ == "__main__":
    sys.exit(main())
