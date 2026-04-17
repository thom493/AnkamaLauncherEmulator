"""Add Account dialog — programmatic PKCE login with Shield support."""

import importlib
import logging

from PyQt6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QVBoxLayout,
)
from qfluentwidgets import (
    BodyLabel,
    CaptionLabel,
    ComboBox,
    LineEdit,
    PasswordLineEdit,
    PrimaryPushButton,
    PushButton,
)

from ankama_launcher_emulator.gui.shield_dialog import ShieldCodeDialog
from ankama_launcher_emulator.gui.utils import run_in_background
from ankama_launcher_emulator.haapi.account_persistence import (
    persist_managed_account,
)
from ankama_launcher_emulator.haapi.pkce_auth import (
    ZaapPkceSession,
    fetch_account_profile,
    programmatic_pkce_login,
)
from ankama_launcher_emulator.haapi.shield import (
    request_security_code,
    store_shield_certificate,
    validate_security_code,
)
from ankama_launcher_emulator.utils.proxy_store import ProxyStore

logger = logging.getLogger()


def _should_use_browser_login(err: object) -> bool:
    message = str(err).lower()
    return (
        "failed to extract csrf state" in message
        or "request blocked" in message
        or "cloudfront" in message
    )


def _load_embedded_auth_dialog_class():
    module = importlib.import_module(
        "ankama_launcher_emulator.gui.embedded_auth_browser_dialog"
    )
    return module.EmbeddedAuthBrowserDialog


class AddAccountDialog(QDialog):
    """Dialog for adding an account via programmatic PKCE login."""

    def __init__(self, proxy_store: ProxyStore, parent=None):
        super().__init__(parent)
        self._proxy_store = proxy_store
        self.setWindowTitle("Add Account")
        self.setMinimumWidth(450)
        self._setup_ui()

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setSpacing(12)
        layout.setContentsMargins(20, 20, 20, 20)

        layout.addWidget(BodyLabel("Login (email)"))
        self._login_input = LineEdit()
        self._login_input.setPlaceholderText("email@example.com")
        layout.addWidget(self._login_input)

        layout.addWidget(BodyLabel("Password"))
        self._password_input = PasswordLineEdit()
        self._password_input.setPlaceholderText("Password")
        layout.addWidget(self._password_input)

        layout.addWidget(BodyLabel("Alias (optional)"))
        self._alias_input = LineEdit()
        self._alias_input.setPlaceholderText("My Alt")
        layout.addWidget(self._alias_input)

        layout.addWidget(BodyLabel("Proxy (optional)"))
        self._proxy_combo = ComboBox()
        self._proxy_combo.addItem("No proxy", userData=None)
        for pid, entry in self._proxy_store.list_proxies().items():
            self._proxy_combo.addItem(entry.name, userData=pid)
        layout.addWidget(self._proxy_combo)

        self._status_label = CaptionLabel("")
        self._status_label.setWordWrap(True)
        layout.addWidget(self._status_label)

        btn_row = QHBoxLayout()
        self._add_btn = PrimaryPushButton("Add Account")
        self._add_btn.clicked.connect(self._on_add)
        btn_row.addWidget(self._add_btn)

        cancel_btn = PushButton("Cancel")
        cancel_btn.clicked.connect(self.reject)
        btn_row.addWidget(cancel_btn)
        layout.addLayout(btn_row)

    def _on_add(self) -> None:
        login = self._login_input.text().strip()
        password = self._password_input.text().strip()
        if not login or not password:
            self._status_label.setText("Login and password required")
            return

        proxy_id = self._proxy_combo.currentData()
        proxy_url = None
        if proxy_id:
            entry = self._proxy_store.get_proxy(proxy_id)
            if entry:
                proxy_url = entry.url

        alias = self._alias_input.text().strip() or None

        self._add_btn.setDisabled(True)
        self._status_label.setText("Logging in...")

        def task(_on_progress: object) -> dict:
            return programmatic_pkce_login(
                login, password, proxy_url=proxy_url, on_progress=self._set_status
            )

        def on_success(result: object) -> None:
            data = dict(result)  # type: ignore[arg-type]
            self._on_login_success(data, login, alias, proxy_url)

        def on_error(err: object) -> None:
            if _should_use_browser_login(err):
                self._start_browser_login(login, alias, proxy_url)
                return
            self._add_btn.setEnabled(True)
            self._status_label.setText(f"Error: {err}")

        run_in_background(task, on_success=on_success, on_error=on_error, parent=self)

    def _start_browser_login(
        self,
        login: str,
        alias: str | None,
        proxy_url: str | None,
    ) -> None:
        self._status_label.setText("Headless login blocked, opening browser...")
        try:
            ShieldBrowserDialog = _load_embedded_auth_dialog_class()
        except (ImportError, RuntimeError) as exc:
            self._add_btn.setEnabled(True)
            self._status_label.setText(
                f"Embedded auth dialog unavailable: {exc}"
            )
            return
        session = ZaapPkceSession()
        dialog = ShieldBrowserDialog(session.auth_url, login, parent=self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            self._add_btn.setEnabled(True)
            self._status_label.setText("Browser login cancelled")
            return

        code = dialog.get_code()
        if not code:
            self._add_btn.setEnabled(True)
            self._status_label.setText("Browser login cancelled")
            return

        self._status_label.setText("Completing browser login...")

        def task(_on_progress: object) -> dict:
            tokens = session.exchange(code)
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
                "proxy_url": proxy_url,
            }

        def on_success(result: object) -> None:
            data = dict(result)  # type: ignore[arg-type]
            self._on_login_success(data, login, alias, proxy_url)

        def on_error(err: object) -> None:
            self._add_btn.setEnabled(True)
            self._status_label.setText(f"Error: {err}")

        run_in_background(task, on_success=on_success, on_error=on_error, parent=self)

    def _set_status(self, msg: str) -> None:
        self._status_label.setText(msg)

    def _on_login_success(
        self,
        data: dict,
        login: str,
        alias: str | None,
        proxy_url: str | None,
    ) -> None:
        security = data.get("security", [])
        needs_shield = "SHIELD" in security or "UNSECURED" in security

        if needs_shield:
            self._handle_shield(data, login, alias)
        else:
            self._persist_account(data, login, alias)
            self._status_label.setText("Account added!")
            self.accept()

    def _handle_shield(self, data: dict, login: str, alias: str | None) -> None:
        # Request security code
        self._status_label.setText("Requesting Shield code via email...")

        def request_code(_on_progress: object) -> None:
            request_security_code(data["access_token"], proxy_url=data.get("proxy_url"))

        def on_code_requested(_result: object) -> None:
            self._show_shield_dialog(data, login, alias)

        def on_error(err: object) -> None:
            self._add_btn.setEnabled(True)
            self._status_label.setText(f"Shield error: {err}")

        run_in_background(
            request_code, on_success=on_code_requested, on_error=on_error, parent=self
        )

    def _show_shield_dialog(self, data: dict, login: str, alias: str | None) -> None:
        dialog = ShieldCodeDialog(
            login,
            parent=self,
            message=(
                f"A security code was sent to the email for {login}.\n"
                "Enter the code below to complete Shield enrollment."
            ),
        )
        if dialog.exec() != QDialog.DialogCode.Accepted:
            self._add_btn.setEnabled(True)
            self._status_label.setText("Shield cancelled")
            return

        code = dialog.get_code()
        if not code:
            self._add_btn.setEnabled(True)
            return

        self._status_label.setText("Validating Shield code...")

        def validate(_on_progress: object) -> dict:
            from ankama_launcher_emulator.decrypter.crypto_helper import CryptoHelper
            _, _, _, hm1, hm2 = CryptoHelper.get_crypto_context(login)
            return validate_security_code(data["access_token"], code, hm1=hm1, hm2=hm2, proxy_url=data.get("proxy_url"))

        def on_validated(cert_data: object) -> None:
            from ankama_launcher_emulator.decrypter.crypto_helper import CryptoHelper
            uuid_active, cert_folder, _, _, _ = CryptoHelper.get_crypto_context(login)
            cert = dict(cert_data)  # type: ignore[arg-type]
            store_shield_certificate(login, cert, cert_folder, uuid_active)
            self._persist_account(data, login, alias)
            self._status_label.setText("Account added with Shield!")
            self.accept()

        def on_error(err: object) -> None:
            self._add_btn.setEnabled(True)
            self._status_label.setText(f"Validation failed: {err}")

        run_in_background(
            validate, on_success=on_validated, on_error=on_error, parent=self
        )

    def _persist_account(
        self,
        data: dict,
        login: str,
        alias: str | None,
    ) -> None:
        persist_managed_account(
            login,
            data["account_id"],
            data["access_token"],
            data.get("refresh_token"),
            alias=alias,
        )
        logger.info(f"[ADD_ACCOUNT] Stored managed account for {login}")
