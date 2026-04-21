"""Add Account dialog — programmatic PKCE login with Shield support."""

import importlib
import logging
import traceback

from PyQt6 import sip
from PyQt6.QtCore import QThread
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
    SwitchButton,
)

from ankama_launcher_emulator.gui.shield_dialog import ShieldCodeDialog
from ankama_launcher_emulator.gui.utils import Worker
from ankama_launcher_emulator.haapi.account_meta import AccountMeta
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
from ankama_launcher_emulator.utils.proxy import to_http_proxy
from ankama_launcher_emulator.utils.proxy_store import ProxyStore

logger = logging.getLogger()


def _should_use_browser_login(err: object) -> bool:
    message = str(err).lower()
    return (
        "failed to extract csrf state" in message
        or "request blocked" in message
        or "cloudfront" in message
        or "waf bypass failed" in message
    )


def _load_embedded_auth_dialog_class():
    module = importlib.import_module(
        "ankama_launcher_emulator.gui.embedded_auth_browser_dialog"
    )
    return module.EmbeddedAuthBrowserDialog


class AddAccountDialog(QDialog):
    """Dialog for adding an account via programmatic PKCE login.

    When `locked_login` is set, operates in reconnect mode: login prefilled
    and read-only, PKCE result must match the locked login.
    """

    def __init__(
        self,
        proxy_store: ProxyStore,
        parent=None,
        locked_login: str | None = None,
        initial_proxy_id: str | None = None,
        initial_alias: str | None = None,
    ):
        super().__init__(parent)
        self._proxy_store = proxy_store
        self._locked_login = locked_login
        self._initial_proxy_id = initial_proxy_id
        self._initial_alias = initial_alias
        # Defer actual close until in-flight background workers finish, so
        # the dialog can't be torn down while a callback is mid-execution.
        self._inflight: int = 0
        self._pending_done: int | None = None
        self._cancelled: bool = False
        # Threads unparented — we own them explicitly and quit+wait on each
        # before finalising done(). Avoids "QThread: Destroyed while still
        # running" if the dialog is deleted before a worker finishes.
        self._threads: list[QThread] = []
        self._workers: list[Worker] = []
        self.setWindowTitle("Reconnect Account" if locked_login else "Add Account")
        self.setMinimumWidth(450)
        self._setup_ui()

    def _run_worker(self, task, on_success, on_error) -> None:
        worker = Worker(task)
        thread = QThread()  # no parent — owned by self._threads
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.finished.connect(thread.quit)

        self._threads.append(thread)
        self._workers.append(worker)
        self._inflight += 1

        def wrapped_success(result: object) -> None:
            try:
                # Guard against the dialog being destroyed (X button, parent
                # window close) while a worker is still in flight — a nested
                # exec() can pump the DeferredDelete event that kills our C++
                # widgets before this callback runs.
                if sip.isdeleted(self) or self._cancelled:
                    return
                on_success(result)
            finally:
                if not sip.isdeleted(self):
                    self._on_worker_done()

        def wrapped_error(err: object) -> None:
            try:
                if sip.isdeleted(self) or self._cancelled:
                    return
                on_error(err)
            finally:
                if not sip.isdeleted(self):
                    self._on_worker_done()

        worker.success.connect(wrapped_success)
        worker.error.connect(wrapped_error)
        thread.start()

    def _on_worker_done(self) -> None:
        self._inflight -= 1
        if self._inflight == 0 and self._pending_done is not None:
            result = self._pending_done
            self._pending_done = None
            self._finalise_done(result)

    def _finalise_done(self, result: int) -> None:
        # Block until every worker thread has fully exited before closing
        # the dialog. Otherwise Qt prints "QThread: Destroyed while thread
        # is still running" and aborts.
        for thread in self._threads:
            thread.quit()
            thread.wait(2000)
        self._threads.clear()
        self._workers.clear()
        super().done(result)

    def done(self, result: int) -> None:
        if result != QDialog.DialogCode.Accepted:
            self._cancelled = True
        if self._inflight > 0:
            self._pending_done = result
            self.hide()
            return
        self._finalise_done(result)

    def closeEvent(self, event) -> None:
        # Symmetric with done(): X button bypasses done(), so without this
        # the C++ dialog would die while a worker is still in flight and
        # its callback would crash on dead child widgets (SwitchButton /
        # Indicator) or dead self.
        if self._inflight > 0:
            event.ignore()
            self._cancelled = True
            self._pending_done = QDialog.DialogCode.Rejected
            self.hide()
            return
        super().closeEvent(event)

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setSpacing(12)
        layout.setContentsMargins(20, 20, 20, 20)

        layout.addWidget(BodyLabel("Login (email)"))
        self._login_input = LineEdit()
        self._login_input.setPlaceholderText("email@example.com")
        if self._locked_login:
            self._login_input.setText(self._locked_login)
            self._login_input.setReadOnly(True)
            self._login_input.setDisabled(True)
        layout.addWidget(self._login_input)

        layout.addWidget(BodyLabel("Password"))
        self._password_input = PasswordLineEdit()
        self._password_input.setPlaceholderText("Password")
        layout.addWidget(self._password_input)

        layout.addWidget(BodyLabel("Alias (optional)"))
        self._alias_input = LineEdit()
        self._alias_input.setPlaceholderText("My Alt")
        if self._initial_alias:
            self._alias_input.setText(self._initial_alias)
        layout.addWidget(self._alias_input)

        layout.addWidget(BodyLabel("Proxy (optional)"))
        self._proxy_combo = ComboBox()
        self._proxy_combo.addItem("No proxy", userData=None)
        for pid, entry in self._proxy_store.list_proxies().items():
            self._proxy_combo.addItem(entry.name, userData=pid)
        if self._initial_proxy_id:
            idx = self._proxy_combo.findData(self._initial_proxy_id)
            if idx >= 0:
                self._proxy_combo.setCurrentIndex(idx)
        layout.addWidget(self._proxy_combo)

        portable_row = QHBoxLayout()
        portable_row.addWidget(BodyLabel("Portable mode (recommended — uses fake hardware fingerprint)"))
        self._portable_switch = SwitchButton(parent=self)
        # Default ON for new accounts. For reconnect, honor the existing entry's setting.
        if self._locked_login:
            existing = AccountMeta().get(self._locked_login) or {}
            self._portable_switch.setChecked(bool(existing.get("portable_mode", True)))
        else:
            self._portable_switch.setChecked(True)
        portable_row.addWidget(self._portable_switch)
        portable_row.addStretch(1)
        layout.addLayout(portable_row)

        self._status_label = CaptionLabel("")
        self._status_label.setWordWrap(True)
        layout.addWidget(self._status_label)

        btn_row = QHBoxLayout()
        self._add_btn = PrimaryPushButton(
            "Reconnect" if self._locked_login else "Add Account"
        )
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
        # Snapshot the switch now — the dialog may go through nested modal
        # exec()s (embedded auth, Shield) before the worker callback runs,
        # and widget C++ lifetimes across those aren't something we control.
        portable = self._portable_switch.isChecked()

        self._add_btn.setDisabled(True)
        self._status_label.setText("Logging in...")

        def task(_on_progress: object) -> dict:
            return programmatic_pkce_login(
                login, password, proxy_url=proxy_url, on_progress=self._set_status
            )

        def on_success(result: object) -> None:
            data = dict(result)  # type: ignore[arg-type]
            self._on_login_success(data, login, alias, proxy_url, portable)

        def on_error(err: object) -> None:
            tb = "".join(traceback.format_exception(type(err), err, getattr(err, "__traceback__", None))) if isinstance(err, BaseException) else ""
            logger.error(
                "[ADD_ACCOUNT] programmatic_pkce_login failed type=%s msg=%r fallback=%s\n%s",
                type(err).__name__, str(err), _should_use_browser_login(err), tb,
            )
            if _should_use_browser_login(err):
                self._start_browser_login(login, alias, proxy_url, portable)
                return
            self._add_btn.setEnabled(True)
            if "incorrect login or password" in str(err).lower():
                self._status_label.setText("Wrong password")
            else:
                self._status_label.setText(f"Error: {err}")

        self._run_worker(task, on_success=on_success, on_error=on_error)

    def _start_browser_login(
        self,
        login: str,
        alias: str | None,
        proxy_url: str | None,
        portable: bool,
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
        # Pass code_verifier so the dialog performs the /token exchange from
        # inside Chromium — avoids AWS WAF TLS-fingerprint 403 that occurs
        # when requests (OpenSSL) sends the exchange with a different JA3 hash.
        # Browser uses HTTP scheme for the same proxy (Chromium can't auth
        # SOCKS5). Same provider exit IP, so login_ip stays consistent with
        # the SOCKS5-routed Python HAAPI session.
        browser_proxy_url = to_http_proxy(proxy_url) if proxy_url else None
        dialog = ShieldBrowserDialog(
            session.auth_url,
            login,
            session.code_verifier,
            parent=self,
            proxy_url=browser_proxy_url,
        )
        result = dialog.exec()
        tokens = dialog.get_tokens()
        token_error = dialog.get_token_error()
        # Queue WebEngine teardown for after the modal loop fully unwinds.
        # Destroying QWebEngineView mid-exit (what WA_DeleteOnClose was doing)
        # corrupts Qt modality state on Windows → main window freezes.
        dialog.deleteLater()

        if result != QDialog.DialogCode.Accepted:
            self._add_btn.setEnabled(True)
            self._status_label.setText("Browser login cancelled")
            return

        if not tokens:
            self._add_btn.setEnabled(True)
            err = token_error or "Token exchange failed"
            self._status_label.setText(f"Error: {err}")
            return

        self._status_label.setText("Completing browser login...")

        def task(_on_progress: object) -> dict:
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
            self._on_login_success(data, login, alias, proxy_url, portable)

        def on_error(err: object) -> None:
            self._add_btn.setEnabled(True)
            self._status_label.setText(f"Error: {err}")

        self._run_worker(task, on_success=on_success, on_error=on_error)

    def _set_status(self, msg: str) -> None:
        self._status_label.setText(msg)

    def _on_login_success(
        self,
        data: dict,
        login: str,
        alias: str | None,
        proxy_url: str | None,
        portable: bool,
    ) -> None:
        if self._locked_login:
            server_login = str(data.get("login") or "")
            if server_login.lower() != self._locked_login.lower():
                self._add_btn.setEnabled(True)
                self._status_label.setText(
                    f"Account mismatch: got {server_login}, expected {self._locked_login}"
                )
                return
            login = self._locked_login

        # Pre-create meta entry with the user's portable-mode choice BEFORE any
        # downstream code (shield validate, persist) calls get_crypto_context.
        # Otherwise that resolves to real Device.getUUID() / createHmEncoders()
        # against the host hardware, which is wrong for portable accounts and
        # also crashes on macOS dev (no /proc/cpuinfo).
        meta = AccountMeta()
        meta.set_meta(login, source="managed", alias=alias)
        meta.set_portable_mode(login, portable)
        if proxy_url is not None:
            meta.set_proxy(login, proxy_url)

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

        self._run_worker(
            request_code, on_success=on_code_requested, on_error=on_error
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

        self._run_worker(
            validate, on_success=on_validated, on_error=on_error
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
