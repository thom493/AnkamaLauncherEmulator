"""Embedded browser dialog for Ankama Shield PKCE authentication.

Opens auth.ankama.com in a QWebEngineView so the user can log in
and complete Shield verification. Intercepts the zaap://login redirect
to extract the authorization code.
"""

from PyQt6.QtCore import QUrl, pyqtSignal
from PyQt6.QtWebEngineCore import QWebEnginePage, QWebEngineProfile
from PyQt6.QtWebEngineWidgets import QWebEngineView
from PyQt6.QtWidgets import QDialog, QVBoxLayout
from qfluentwidgets import BodyLabel


class _ShieldPage(QWebEnginePage):
    """Custom page that intercepts zaap:// redirects."""

    code_received = pyqtSignal(str)

    def acceptNavigationRequest(
        self, url: QUrl, type: QWebEnginePage.NavigationType, isMainFrame: bool
    ) -> bool:
        if url.scheme() == "zaap" and url.host() == "login":
            from PyQt6.QtCore import QUrlQuery

            query = QUrlQuery(url)
            code = query.queryItemValue("code")
            if code:
                self.code_received.emit(code)
            return False
        return True


class ShieldBrowserDialog(QDialog):
    """Dialog embedding Chromium for PKCE login + Shield flow.

    Opens the PKCE auth URL. When the user completes login,
    auth.ankama.com redirects to zaap://login?code=XXX.
    We intercept that and store the code.
    """

    def __init__(self, auth_url: str, login: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Shield Verification")
        self.setMinimumSize(800, 700)
        self._auth_code: str | None = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)

        info = BodyLabel(
            f"Log in as {login} to authorize this proxy IP.\n"
            "The window will close automatically after login."
        )
        info.setWordWrap(True)
        layout.addWidget(info)

        profile = QWebEngineProfile(self)
        self._page = _ShieldPage(profile, self)
        self._page.code_received.connect(self._on_code)

        self._browser = QWebEngineView(self)
        self._browser.setPage(self._page)
        layout.addWidget(self._browser, 1)

        self._browser.setUrl(QUrl(auth_url))

    def _on_code(self, code: str) -> None:
        self._auth_code = code
        self.accept()

    def get_code(self) -> str | None:
        return self._auth_code
