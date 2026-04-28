from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import QDialog, QVBoxLayout
from qfluentwidgets import BodyLabel, LineEdit, PrimaryPushButton, PushButton

_MAX_RESEND = 3


class ShieldCodeDialog(QDialog):
    """Dialog asking user for Ankama Shield security code.

    A security code has been sent to the user's email.
    They enter it here, we validate via HAAPI through the proxy.
    """

    resend_requested = pyqtSignal()

    def __init__(
        self,
        login: str,
        parent=None,
        message: str | None = None,
        placeholder: str | None = None,
    ):
        super().__init__(parent)
        self.setWindowTitle("Shield Verification")
        self.setMinimumWidth(400)
        self._code: str | None = None
        self._resend_count = 0
        self._setup_ui(login, message, placeholder)

    def _setup_ui(
        self,
        login: str,
        message: str | None = None,
        placeholder: str | None = None,
    ) -> None:
        layout = QVBoxLayout(self)
        layout.setSpacing(12)
        layout.setContentsMargins(20, 20, 20, 20)

        default_msg = (
            f"New proxy IP detected for {login}.\n\n"
            "Ankama sent a security code to your email.\n"
            "Enter it below to authorize this proxy."
        )
        info = BodyLabel(message or default_msg)
        info.setWordWrap(True)
        layout.addWidget(info)

        self._code_input = LineEdit()
        self._code_input.setPlaceholderText(placeholder or "Security code from email")
        self._code_input.returnPressed.connect(self._on_submit)
        layout.addWidget(self._code_input)

        self._submit_btn = PrimaryPushButton("Validate")
        self._submit_btn.clicked.connect(self._on_submit)
        layout.addWidget(self._submit_btn)

        self._resend_btn = PushButton("Resend code")
        self._resend_btn.clicked.connect(self._on_resend)
        layout.addWidget(self._resend_btn)

        self._proxy_warning = BodyLabel(
            "No email received after multiple attempts.\n"
            "Your proxy may be blocked by Ankama — consider changing it."
        )
        self._proxy_warning.setWordWrap(True)
        self._proxy_warning.setStyleSheet("color: #e8a04a;")
        self._proxy_warning.setVisible(False)
        layout.addWidget(self._proxy_warning)

        cancel_btn = PushButton("Cancel")
        cancel_btn.clicked.connect(self.reject)
        layout.addWidget(cancel_btn)

    def _on_resend(self) -> None:
        self._resend_count += 1
        self._resend_btn.setEnabled(False)
        self._resend_btn.setText("Sending...")
        self.resend_requested.emit()
        if self._resend_count >= _MAX_RESEND:
            self._proxy_warning.setVisible(True)

    def resend_done(self, success: bool) -> None:
        """Call after resend background task completes to re-enable the button."""
        self._resend_btn.setEnabled(True)
        self._resend_btn.setText("Resend code")
        if not success:
            self._proxy_warning.setVisible(True)

    def _on_submit(self) -> None:
        code = self._code_input.text().strip()
        if not code:
            return
        self._code = code
        self.accept()

    def get_code(self) -> str | None:
        return self._code
