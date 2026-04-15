import webbrowser

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QDialog, QLabel, QVBoxLayout
from qfluentwidgets import BodyLabel, LineEdit, PrimaryPushButton, PushButton


class ShieldDialog(QDialog):
    """Dialog for PKCE Shield verification.

    Opens system browser with auth URL, user pastes back the code.
    """

    def __init__(self, auth_url: str, login: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Shield Verification")
        self.setMinimumWidth(500)
        self._auth_url = auth_url
        self._code: str | None = None
        self._setup_ui(login)

    def _setup_ui(self, login: str) -> None:
        layout = QVBoxLayout(self)
        layout.setSpacing(12)
        layout.setContentsMargins(20, 20, 20, 20)

        info = BodyLabel(
            f"Proxy IP needs Shield verification for {login}.\n\n"
            "1. Click 'Open Browser' below\n"
            "2. Log in with your Ankama credentials\n"
            "3. Complete Shield verification (check your email)\n"
            "4. After login, browser will try to open zaap://login?code=...\n"
            "5. Copy the 'code' value from the URL bar and paste it below"
        )
        info.setWordWrap(True)
        layout.addWidget(info)

        self._open_btn = PrimaryPushButton("Open Browser")
        self._open_btn.clicked.connect(self._open_browser)
        layout.addWidget(self._open_btn)

        url_label = BodyLabel("Or copy this URL manually:")
        url_label.setStyleSheet("color: gray; font-size: 11px;")
        layout.addWidget(url_label)

        self._url_display = LineEdit()
        self._url_display.setText(self._auth_url)
        self._url_display.setReadOnly(True)
        layout.addWidget(self._url_display)

        code_label = BodyLabel("Paste authorization code:")
        layout.addWidget(code_label)

        self._code_input = LineEdit()
        self._code_input.setPlaceholderText("Code from zaap://login?code=...")
        layout.addWidget(self._code_input)

        self._submit_btn = PrimaryPushButton("Validate")
        self._submit_btn.clicked.connect(self._on_submit)
        layout.addWidget(self._submit_btn)

        cancel_btn = PushButton("Cancel")
        cancel_btn.clicked.connect(self.reject)
        layout.addWidget(cancel_btn)

    def _open_browser(self) -> None:
        webbrowser.open(self._auth_url)

    def _on_submit(self) -> None:
        code = self._code_input.text().strip()
        if not code:
            return
        # Handle if user pasted full URL instead of just code
        if "code=" in code:
            for part in code.split("?")[-1].split("&"):
                if part.startswith("code="):
                    code = part[5:]
                    break
        self._code = code
        self.accept()

    def get_code(self) -> str | None:
        return self._code
