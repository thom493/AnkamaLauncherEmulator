"""Embedded browser dialog for Ankama PKCE authentication."""

from PyQt6.QtCore import QUrl, pyqtSignal
from PyQt6.QtWidgets import QDialog, QVBoxLayout
from qfluentwidgets import BodyLabel


def _build_embedded_auth_page_class():
    from PyQt6.QtWebEngineCore import QWebEnginePage

    class _EmbeddedAuthPage(QWebEnginePage):
        """Intercept zaap://login redirects and extract the auth code."""

        code_received = pyqtSignal(str)

        def acceptNavigationRequest(
            self,
            url: QUrl,
            navigation_type: QWebEnginePage.NavigationType,
            is_main_frame: bool,
        ) -> bool:
            del navigation_type, is_main_frame
            if url.scheme() == "zaap" and url.host() == "login":
                from PyQt6.QtCore import QUrlQuery

                query = QUrlQuery(url)
                code = query.queryItemValue("code")
                if code:
                    self.code_received.emit(code)
                return False
            return True

    return _EmbeddedAuthPage


class EmbeddedAuthBrowserDialog(QDialog):
    """Dialog embedding Chromium for PKCE login and redirect capture."""

    def __init__(self, auth_url: str, login: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Authentication")
        self.setMinimumSize(800, 700)
        self._auth_code: str | None = None

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
        profile = QWebEngineProfile(self)
        self._page = embedded_auth_page_class(profile, self)
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
