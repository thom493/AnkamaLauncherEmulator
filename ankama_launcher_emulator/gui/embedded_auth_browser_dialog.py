"""Embedded browser dialog for Ankama PKCE authentication.

Token exchange is performed inside Chromium via JS fetch() to avoid
AWS WAF TLS-fingerprint mismatch that causes 403 when using requests.

Result is signaled back from JS via document.title — Chromium silently
drops navigations to unregistered custom URL schemes (the previous
qt-token-result:// approach), so the title channel is used instead.
"""

import json
import logging
from urllib.parse import quote, unquote, urlparse

from PyQt6.QtCore import QTimer, QUrl, pyqtSignal
from PyQt6.QtWidgets import QDialog, QVBoxLayout
from qfluentwidgets import BodyLabel

from ankama_launcher_emulator.gui.style import apply_dark_dialog_style

logger = logging.getLogger(__name__)

_AUTH_TOKEN_URL = "https://auth.ankama.com/token"
_ZAAP_CLIENT_ID = 102
_ZAAP_REDIRECT_URI = "zaap://login"
_TITLE_PREFIX = "__TOKEN__:"


def _build_embedded_auth_page_class():
    from PyQt6.QtWebEngineCore import QWebEnginePage

    class _EmbeddedAuthPage(QWebEnginePage):
        """Intercept zaap://login navigations and emit token result on titleChanged."""

        code_received = pyqtSignal(str)
        token_exchange_done = pyqtSignal(int, str)  # http_status, body

        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self._seen_code: str | None = None
            self.titleChanged.connect(self._on_title_changed)

        def acceptNavigationRequest(
            self,
            url: QUrl,
            navigation_type: QWebEnginePage.NavigationType,
            is_main_frame: bool,
        ) -> bool:
            del navigation_type, is_main_frame
            scheme = url.scheme()

            if scheme == "zaap" and url.host() == "login":
                from PyQt6.QtCore import QUrlQuery
                query = QUrlQuery(url)
                code = query.queryItemValue("code")
                if code and code != self._seen_code:
                    self._seen_code = code
                    self.code_received.emit(code)
                return False

            return True

        def _on_title_changed(self, title: str) -> None:
            if not title.startswith(_TITLE_PREFIX):
                return
            payload = title[len(_TITLE_PREFIX):]
            try:
                sep = payload.index(":")
                status = int(payload[:sep])
            except (ValueError, IndexError):
                logger.warning("[PKCE/browser] malformed token title: %s", title[:120])
                return
            body = unquote(payload[sep + 1:])
            self.token_exchange_done.emit(status, body)

    return _EmbeddedAuthPage


class EmbeddedAuthBrowserDialog(QDialog):
    """Dialog embedding Chromium for PKCE login, code capture, and in-browser token exchange.

    When `code_verifier` is supplied the dialog performs the /token POST from
    inside Chromium (same WAF session / TLS fingerprint) and exposes the result
    via `get_tokens()`.  Callers should not call `session.exchange()` separately.
    """

    def __init__(
        self,
        auth_url: str,
        login: str,
        code_verifier: str | None = None,
        parent=None,
        proxy_url: str | None = None,
    ):
        super().__init__(parent)
        # Caller schedules deleteLater() AFTER exec() returns — tearing down
        # a QWebEngineView mid-exit (what WA_DeleteOnClose would do) corrupts
        # Qt modality state on Windows and freezes the parent window.
        self.setWindowTitle("Authentication")
        self.setMinimumSize(800, 700)
        apply_dark_dialog_style(self)
        self._auth_code: str | None = None
        self._code_verifier = code_verifier
        self._tokens: dict | None = None
        self._token_error: str | None = None
        self._cookies: dict[str, str] = {}

        # Route Chromium through the same proxy exit as the Python HAAPI
        # session. Otherwise /Account/Account records the host's real IP as
        # login_ip and the subsequent /Shield/SecurityCode call from the
        # proxied requests session is rejected ("Unauthorized service
        # '\Ankama\Shield'") because the IPs don't match.
        #
        # Caller passes an http://user:pass@host:port URL (most providers
        # serve HTTP and SOCKS5 on the same exit). HTTP is required because
        # Chromium does not support SOCKS5 username/password auth — the URL
        # creds are stripped before being passed to the network stack. HTTP
        # auth, in contrast, is delegated back to Qt via the
        # proxyAuthenticationRequired signal which we handle below.
        self._proxy_user = ""
        self._proxy_password = ""
        self._previous_proxy = self._apply_http_proxy(proxy_url)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)

        info = BodyLabel(
            f"Log in as {login} in the embedded launcher browser.\n"
            "This window will close automatically after authentication."
        )
        info.setWordWrap(True)
        layout.addWidget(info)

        from PyQt6.QtWebEngineCore import QWebEngineProfile
        from PyQt6.QtWebEngineWidgets import QWebEngineView

        embedded_auth_page_class = _build_embedded_auth_page_class()
        self._profile = QWebEngineProfile(self)
        self._profile.cookieStore().cookieAdded.connect(self._on_cookie_added)
        self._page = embedded_auth_page_class(self._profile, self)
        self._page.code_received.connect(self._on_code)
        self._page.token_exchange_done.connect(self._on_token_exchange_done)
        if self._proxy_user:
            self._page.proxyAuthenticationRequired.connect(self._on_proxy_auth)

        self._browser = QWebEngineView(self)
        self._browser.setPage(self._page)
        layout.addWidget(self._browser, 1)
        self._browser.setUrl(QUrl(auth_url))

    def _apply_http_proxy(self, proxy_url: str | None):
        if not proxy_url:
            return None
        parsed = urlparse(proxy_url)
        if parsed.scheme != "http" or not parsed.hostname:
            logger.warning(
                "[PKCE/browser] unsupported proxy scheme for browser: %s "
                "(expected http://)", parsed.scheme,
            )
            return None
        from PyQt6.QtNetwork import QNetworkProxy

        self._proxy_user = parsed.username or ""
        self._proxy_password = parsed.password or ""

        previous = QNetworkProxy.applicationProxy()
        # Chromium strips creds from the URL it receives via --proxy-server,
        # so we still set them on the QNetworkProxy for completeness but
        # the actual auth is delivered via proxyAuthenticationRequired.
        proxy = QNetworkProxy(
            QNetworkProxy.ProxyType.HttpProxy,
            parsed.hostname,
            parsed.port or 8080,
            self._proxy_user,
            self._proxy_password,
        )
        QNetworkProxy.setApplicationProxy(proxy)
        logger.info(
            "[PKCE/browser] Chromium routed via HTTP proxy %s:%s",
            parsed.hostname,
            parsed.port,
        )
        return previous

    def _on_proxy_auth(self, _request_url, authenticator, _proxy_host) -> None:
        # Fires on Chromium's first 407 from the proxy. Without this, the
        # CONNECT retries indefinitely and the page never loads.
        authenticator.setUser(self._proxy_user)
        authenticator.setPassword(self._proxy_password)

    # ------------------------------------------------------------------
    # Cookie capture
    # ------------------------------------------------------------------

    def _on_cookie_added(self, cookie) -> None:
        domain = (
            bytes(cookie.domain()).decode("ascii", errors="ignore")
            if isinstance(cookie.domain(), (bytes, bytearray))
            else str(cookie.domain())
        )
        if "ankama" not in domain.lower():
            return
        name = bytes(cookie.name()).decode("ascii", errors="ignore")
        value = bytes(cookie.value()).decode("ascii", errors="ignore")
        if name:
            self._cookies[name] = value

    # ------------------------------------------------------------------
    # PKCE code capture → in-browser token exchange
    # ------------------------------------------------------------------

    def _on_code(self, code: str) -> None:
        self._auth_code = code
        if self._code_verifier:
            # Exchange inside Chromium: avoids WAF TLS-fingerprint mismatch
            QTimer.singleShot(0, lambda: self._exchange_in_browser(code))
        else:
            # Legacy path: caller does the exchange externally
            QTimer.singleShot(0, self.accept)

    def _exchange_in_browser(self, code: str) -> None:
        """Inject a JS fetch() POST to /token while still inside the browser session.

        auth.ankama.com/token is same-origin from the auth page, so CORS
        is not a concern. The result is signaled back via document.title
        which the page's titleChanged signal forwards to token_exchange_done.
        """
        payload = (
            f"grant_type=authorization_code"
            f"&code={quote(code, safe='')}"
            f"&redirect_uri={quote(_ZAAP_REDIRECT_URI, safe='')}"
            f"&client_id={_ZAAP_CLIENT_ID}"
            f"&code_verifier={quote(self._code_verifier or '', safe='')}"
        )
        # Triple-quoted f-string: {{ → { and }} → } so brace nesting is explicit.
        # .then/.catch hang off fetch() directly; IIFE body closes last via }}).
        js = f"""(function(){{
    fetch('{_AUTH_TOKEN_URL}', {{
        method: 'POST',
        headers: {{'Content-Type': 'application/x-www-form-urlencoded'}},
        body: '{payload}'
    }}).then(function(r){{
        return r.text().then(function(t){{ return [r.status, t]; }});
    }}).then(function(pair){{
        document.title = '{_TITLE_PREFIX}' + pair[0] + ':' + encodeURIComponent(pair[1]);
    }}).catch(function(e){{
        document.title = '{_TITLE_PREFIX}0:' + encodeURIComponent('err:' + String(e));
    }});
}})();"""
        self._page.runJavaScript(js)

    def _on_token_exchange_done(self, status: int, body: str) -> None:
        if status == 200:
            try:
                data = json.loads(body)
                if "access_token" in data:
                    self._tokens = data
                else:
                    self._token_error = f"Token response missing access_token: {body[:200]}"
            except Exception as exc:
                self._token_error = f"Token JSON parse error: {exc}: {body[:200]}"
        else:
            self._token_error = f"HTTP {status}: {body[:300]}"
            logger.warning("[PKCE/browser] Token exchange failed %s: %s", status, body[:200])

        QTimer.singleShot(0, self.accept)

    # ------------------------------------------------------------------
    # Public accessors
    # ------------------------------------------------------------------

    def get_code(self) -> str | None:
        return self._auth_code

    def get_cookies(self) -> dict[str, str]:
        return dict(self._cookies)

    def get_tokens(self) -> dict | None:
        """Return {access_token, refresh_token} dict if exchange succeeded, else None."""
        return self._tokens

    def get_token_error(self) -> str | None:
        return self._token_error

    # ------------------------------------------------------------------
    # Teardown
    # ------------------------------------------------------------------

    def done(self, result: int) -> None:
        # Chromium requires: page destroyed before profile.
        # Strategy:
        #   1. Give browser a dummy page so it releases our custom page.
        #   2. deleteLater the custom page.
        #   3. Connect page.destroyed → profile.deleteLater so profile is
        #      deleted only AFTER the page DeferredDelete event fires.
        # Without this the profile can be destroyed with a live page still
        # registered → "Release of profile requested but WebEnginePage still
        # not deleted" → renderer crash → GUI freeze.
        from PyQt6.QtWebEngineCore import QWebEnginePage

        if self._browser is not None:
            dummy = QWebEnginePage(self._browser)  # browser owns dummy
            self._browser.setPage(dummy)

        if self._page is not None:
            page = self._page
            self._page = None
            page.setParent(None)
            if self._profile is not None:
                profile = self._profile
                self._profile = None
                profile.setParent(None)
                # Delete profile only after page is fully destroyed
                page.destroyed.connect(lambda: QTimer.singleShot(0, profile.deleteLater))
            page.deleteLater()
        elif self._profile is not None:
            profile = self._profile
            self._profile = None
            profile.setParent(None)
            QTimer.singleShot(0, profile.deleteLater)

        if self._previous_proxy is not None:
            from PyQt6.QtNetwork import QNetworkProxy

            QNetworkProxy.setApplicationProxy(self._previous_proxy)
            self._previous_proxy = None

        super().done(result)
