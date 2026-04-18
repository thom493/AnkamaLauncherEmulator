"""Embedded browser dialog for Ankama PKCE authentication.

Token exchange is performed inside Chromium via JS fetch() to avoid
AWS WAF TLS-fingerprint mismatch that causes 403 when using requests.
"""

import json
import logging
from urllib.parse import quote

from PyQt6.QtCore import QTimer, QUrl, pyqtSignal
from PyQt6.QtWidgets import QDialog, QVBoxLayout
from qfluentwidgets import BodyLabel

logger = logging.getLogger(__name__)

_AUTH_TOKEN_URL = "https://auth.ankama.com/token"
_ZAAP_CLIENT_ID = 102
_ZAAP_REDIRECT_URI = "zaap://login"
_RESULT_SCHEME = "qt-token-result"


def _build_embedded_auth_page_class():
    from PyQt6.QtWebEngineCore import QWebEnginePage

    class _EmbeddedAuthPage(QWebEnginePage):
        """Intercept zaap://login and qt-token-result:// navigations."""

        code_received = pyqtSignal(str)
        token_exchange_done = pyqtSignal(int, str)  # http_status, body

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
                if code:
                    self.code_received.emit(code)
                return False

            if scheme == _RESULT_SCHEME:
                # qt-token-result://{status}/{percent-encoded-body}
                try:
                    status = int(url.host() or "0")
                except ValueError:
                    status = 0
                encoded_body = url.path().lstrip("/")
                body = QUrl.fromPercentEncoding(encoded_body.encode("ascii", errors="replace"))
                self.token_exchange_done.emit(status, body)
                return False

            return True

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
    ):
        super().__init__(parent)
        self.setWindowTitle("Authentication")
        self.setMinimumSize(800, 700)
        self._auth_code: str | None = None
        self._code_verifier = code_verifier
        self._tokens: dict | None = None
        self._token_error: str | None = None
        self._cookies: dict[str, str] = {}

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

        self._browser = QWebEngineView(self)
        self._browser.setPage(self._page)
        layout.addWidget(self._browser, 1)
        self._browser.setUrl(QUrl(auth_url))

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
        is not a concern. The result is signaled back via qt-token-result://
        navigation which acceptNavigationRequest intercepts.
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
        window.location.href = '{_RESULT_SCHEME}://' + pair[0] + '/' + encodeURIComponent(pair[1]);
    }}).catch(function(e){{
        window.location.href = '{_RESULT_SCHEME}://0/' + encodeURIComponent('err:' + String(e));
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

        super().done(result)
