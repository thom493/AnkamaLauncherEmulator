import logging
from typing import Callable, cast

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtWidgets import (
    QDialog,
    QFrame,
    QHBoxLayout,
    QMainWindow,
    QMessageBox,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)
from qfluentwidgets import (
    BodyLabel,
    CaptionLabel,
    CardWidget,
    InfoBar,
    InfoBarPosition,
    PushButton,
    TitleLabel,
)

from ankama_launcher_emulator.consts import (
    CYTRUS_INSTALLED,
    DOFUS_INSTALLED,
    RESOURCES,
    RETRO_INSTALLED,
    ZAAP_PATH,
)
from ankama_launcher_emulator.decrypter.crypto_helper import CryptoHelper
from ankama_launcher_emulator.gui.account_card import AccountCard
from ankama_launcher_emulator.gui.consts import (
    APP_BG_HEXA,
    BORDER_HEXA,
    DOFUS_3_TITLE,
    DOFUS_RETRO_TITLE,
    ORANGE_HEXA,
    PANEL_ALT_HEXA,
    PANEL_BG_HEXA,
    RED_HEXA,
    TEXT_MUTED_HEXA,
)
from ankama_launcher_emulator.gui.download_banner import DownloadBanner
from ankama_launcher_emulator.gui.game_selector_card import GameSelectorCard
from ankama_launcher_emulator.gui.proxy_dialog import ProxyDialog
from ankama_launcher_emulator.gui.shield_dialog import ShieldCodeDialog
from ankama_launcher_emulator.gui.star_dialog import (
    StarBar,
    has_shown_star_repo,
)
from ankama_launcher_emulator.gui.utils import run_in_background
from ankama_launcher_emulator.haapi.account_manager import remove_account
from ankama_launcher_emulator.haapi.shield import (
    ShieldRequired,
    ShieldRecoveryRequired,
    check_proxy_needs_shield,
    request_security_code,
    store_shield_certificate,
    validate_security_code,
)
from ankama_launcher_emulator.server.server import AnkamaLauncherServer
from ankama_launcher_emulator.utils.internet import get_available_network_interfaces
from ankama_launcher_emulator.utils.proxy import build_proxy_listener, verify_proxy_ip
from ankama_launcher_emulator.utils.proxy_store import ProxyStore

logger = logging.getLogger()


class MainWindow(QMainWindow):
    def __init__(
        self,
        server: AnkamaLauncherServer,
        accounts: list,
        all_interface: dict[str, tuple[str, str]],
    ):
        super().__init__()
        self._server = server
        self._accounts: list = accounts
        self._interfaces: dict[str, tuple[str, str]] = all_interface
        self._proxy_store = ProxyStore()
        self._cards: list[AccountCard] = []
        self._current_game_is_dofus3: bool = DOFUS_INSTALLED or not RETRO_INSTALLED
        self._is_refreshing = False
        server_handler = getattr(self._server, "handler", None)
        if server_handler is not None:
            server_handler.on_shield_recovery = self._on_server_shield_recovery
        self._setup_ui(accounts, all_interface)
        self._start_refresh_timer()

    def _setup_ui(self, accounts: list, all_interface: dict) -> None:
        self.setWindowTitle("AnkAlt Launcher")
        self.setMinimumWidth(1080)
        self.resize(1240, 760)
        self.setStyleSheet(
            "MainWindow {"
            f"background-color: {APP_BG_HEXA};"
            "}"
            f"QWidget#sidebar {{ background-color: {PANEL_BG_HEXA}; border-right: 1px solid {BORDER_HEXA}; }}"
            f"QWidget#contentShell {{ background-color: {APP_BG_HEXA}; }}"
            f"QWidget#topBar {{ background-color: {PANEL_BG_HEXA}; border: 1px solid {BORDER_HEXA}; border-radius: 20px; }}"
            f"QWidget#topBar CaptionLabel {{ color: {TEXT_MUTED_HEXA}; }}"
            f"CardWidget#warningCard {{ background-color: {PANEL_ALT_HEXA}; border: 1px solid {BORDER_HEXA}; border-radius: 18px; }}"
            f"CardWidget#emptyStateCard {{ background-color: {PANEL_BG_HEXA}; border: 1px solid {BORDER_HEXA}; border-radius: 20px; }}"
            f"CardWidget#emptyStateCard BodyLabel {{ color: {TEXT_MUTED_HEXA}; }}"
        )

        central = QWidget()
        self.setCentralWidget(central)

        root_layout = QHBoxLayout(central)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)

        self._dofus_selector = GameSelectorCard(
            DOFUS_3_TITLE, RESOURCES / "Dofus3.png", False, available=DOFUS_INSTALLED
        )
        self._retro_selector = GameSelectorCard(
            DOFUS_RETRO_TITLE,
            RESOURCES / "DofusRetro.png",
            False,
            available=RETRO_INSTALLED,
        )
        self._dofus_selector.clicked.connect(lambda: self._select_game(True))
        self._retro_selector.clicked.connect(lambda: self._select_game(False))

        self._sidebar = QWidget()
        self._sidebar.setObjectName("sidebar")
        sidebar_layout = QVBoxLayout(self._sidebar)
        sidebar_layout.setContentsMargins(14, 18, 14, 18)
        sidebar_layout.setSpacing(12)
        sidebar_layout.addWidget(self._dofus_selector)
        sidebar_layout.addWidget(self._retro_selector)
        sidebar_layout.addStretch()
        root_layout.addWidget(self._sidebar)

        content_shell = QWidget()
        content_shell.setObjectName("contentShell")
        layout = QVBoxLayout(content_shell)
        layout.setContentsMargins(24, 20, 24, 24)
        layout.setSpacing(14)
        root_layout.addWidget(content_shell, 1)

        self._top_bar = QWidget()
        self._top_bar.setObjectName("topBar")
        top_bar_layout = QHBoxLayout(self._top_bar)
        top_bar_layout.setContentsMargins(20, 18, 20, 18)
        top_bar_layout.setSpacing(16)

        title_stack = QVBoxLayout()
        title_stack.setSpacing(2)

        top_label = CaptionLabel("Selected Game")
        self._title_label = TitleLabel(
            DOFUS_3_TITLE if self._current_game_is_dofus3 else DOFUS_RETRO_TITLE
        )
        self._title_label.setAlignment(Qt.AlignmentFlag.AlignLeft)
        self._subtitle_label = BodyLabel("Launch accounts, proxies, and network routes.")
        self._subtitle_label.setStyleSheet(f"color: {TEXT_MUTED_HEXA};")

        title_stack.addWidget(top_label)
        title_stack.addWidget(self._title_label)
        title_stack.addWidget(self._subtitle_label)
        top_bar_layout.addLayout(title_stack, 1)

        action_row = QHBoxLayout()
        action_row.setSpacing(10)

        gear_btn = PushButton("Proxies")
        gear_btn.setFixedWidth(100)
        gear_btn.clicked.connect(self._open_proxy_dialog)
        action_row.addWidget(gear_btn)

        add_btn = PushButton("Add Account")
        add_btn.setFixedWidth(124)
        add_btn.setStyleSheet(
            "PushButton {"
            f"background-color: {ORANGE_HEXA};"
            "color: white;"
            "border-radius: 10px;"
            "padding: 8px 14px;"
            "}"
        )
        add_btn.clicked.connect(self._open_add_account_dialog)
        action_row.addWidget(add_btn)
        top_bar_layout.addLayout(action_row)

        layout.addWidget(self._top_bar)

        if not has_shown_star_repo():
            layout.addWidget(StarBar())

        if not CYTRUS_INSTALLED:
            self._warning_card = CardWidget()
            self._warning_card.setObjectName("warningCard")
            warning_layout = QVBoxLayout(self._warning_card)
            warning_layout.setContentsMargins(18, 16, 18, 16)
            warning_layout.setSpacing(4)
            warning_layout.addWidget(BodyLabel("cytrus-v6 is not installed"))
            warning_hint = CaptionLabel(
                "Auto-update will not work. Install it with: npm install -g cytrus-v6"
            )
            warning_hint.setWordWrap(True)
            warning_layout.addWidget(warning_hint)
            layout.addWidget(self._warning_card)
        else:
            self._warning_card = None

        self._banner = DownloadBanner()
        layout.addWidget(self._banner)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)

        self._card_container = QWidget()
        self._card_layout = QVBoxLayout(self._card_container)
        self._card_layout.setContentsMargins(0, 4, 0, 4)
        self._card_layout.setSpacing(10)

        self._empty_state_card = CardWidget()
        self._empty_state_card.setObjectName("emptyStateCard")
        empty_layout = QVBoxLayout(self._empty_state_card)
        empty_layout.setContentsMargins(28, 28, 28, 28)
        empty_layout.setSpacing(8)
        empty_layout.addWidget(TitleLabel("No account found"))
        self._empty_state_label = BodyLabel(
            "No account found.\n"
            "Check that Ankama Launcher is installed and has logged accounts.\n"
            f"Expected path: {ZAAP_PATH}/keydata/\n\n"
            "Or click 'Add Account' to add an account manually."
        )
        self._empty_state_label.setWordWrap(True)
        self._empty_state_label.setStyleSheet(f"color: {RED_HEXA};")
        empty_layout.addWidget(self._empty_state_label)
        self._card_layout.addWidget(self._empty_state_card)

        for account in accounts:
            self._add_card(account, all_interface)

        self._card_layout.addStretch()
        scroll.setWidget(self._card_container)
        layout.addWidget(scroll, 1)

        self._select_game(self._current_game_is_dofus3)
        self._sync_empty_state()

    def _select_game(self, is_dofus_3: bool) -> None:
        self._current_game_is_dofus3 = is_dofus_3
        self._title_label.setText(DOFUS_3_TITLE if is_dofus_3 else DOFUS_RETRO_TITLE)
        self._subtitle_label.setText(
            "Launch accounts, proxies, and network routes."
            if is_dofus_3
            else "Launch Retro accounts with the same per-account controls."
        )
        self._dofus_selector.set_active(is_dofus_3)
        self._retro_selector.set_active(not is_dofus_3)

    def _current_launch_fn(self) -> Callable:
        if self._current_game_is_dofus3:
            return self._launch_dofus
        return self._launch_retro

    def _add_card(self, account: dict, all_interface: dict) -> AccountCard:
        login = account["apikey"]["login"]
        card = AccountCard(
            login, all_interface, self._proxy_store, self._card_container
        )
        self._cards.append(card)
        card.launch_requested.connect(self._make_launch_handler(login, card))
        card.remove_requested.connect(
            lambda l=login, c=card: self._on_remove_account(l, c)
        )
        card.error_occurred.connect(self._show_error)
        self._card_layout.insertWidget(self._card_layout.count() - 1, card)
        self._sync_empty_state()
        return card

    def _set_panel_status(self, text: str) -> None:
        was_visible = self._banner.isVisible()
        self._banner.set_status(text)
        if not text:
            for card in self._cards:
                card.set_launch_enabled(True)
        elif not was_visible:
            for card in self._cards:
                card.set_launch_enabled(False)

    def _sync_empty_state(self) -> None:
        self._empty_state_card.setVisible(not self._cards)

    def _find_card(self, login: str) -> AccountCard | None:
        for card in self._cards:
            if card.login == login:
                return card
        return None

    def _make_launch_handler(
        self,
        login: str,
        card: AccountCard,
    ) -> Callable[[object, object], None]:
        def handler(iface: object, proxy_id: object) -> None:
            launch = self._current_launch_fn()
            proxy_url = self._proxy_store.get_proxy_url(login) if proxy_id else None

            def on_success(result: object) -> None:
                self._show_success(f"Game launch for {login}")
                self._set_panel_status("")
                card.set_running(int(result))  # type: ignore[arg-type]

            def on_error(err: object) -> None:
                if isinstance(err, ShieldRecoveryRequired):
                    self._set_panel_status("")
                    self._handle_shield_recovery(err, launch, card)
                    return
                if isinstance(err, ShieldRequired):
                    self._set_panel_status("")
                    self._handle_shield(err, launch, card)
                    return
                self._show_error(str(err))
                self._set_panel_status("")
                card.set_launch_enabled(True)

            run_in_background(
                lambda on_progress: launch(
                    login,
                    cast(str | None, iface),
                    proxy_url,
                    on_progress=on_progress,
                ),
                on_success=on_success,
                on_error=on_error,
                on_progress=self._set_panel_status,
                parent=self,
            )

        return handler

    def _handle_shield(
        self,
        err: ShieldRequired,
        launch: Callable,
        card: AccountCard,
    ) -> None:
        """Handle Shield for existing accounts using stored API key directly.

        No browser PKCE needed — use the stored key for SecurityCode/ValidateCode.
        auth.ankama.com/token rejects redirect_uri=http://127.0.0.1:... (not registered
        for client_id=102, only zaap://login is). So skip /token entirely.
        """
        self._set_panel_status("Requesting Shield code via email...")

        def request_code(on_progress: Callable) -> str:
            api_key = CryptoHelper.getStoredApiKey(err.login)["apikey"]["key"]
            on_progress("Requesting security code via email...")
            request_security_code(api_key)
            logger.info("[SHIELD] Security code requested via email")
            return api_key

        def on_code_requested(result: object) -> None:
            api_key = str(result)
            self._set_panel_status("")
            self._show_shield_code_dialog(err, api_key, launch, card)

        def on_error(exc: object) -> None:
            self._show_error(f"Shield error: {exc}")
            self._set_panel_status("")
            card.set_launch_enabled(True)

        run_in_background(
            request_code,
            on_success=on_code_requested,
            on_error=on_error,
            on_progress=self._set_panel_status,
            parent=self,
        )

    def _handle_shield_recovery(
        self,
        err: ShieldRecoveryRequired,
        launch: Callable,
        card: AccountCard,
    ) -> None:
        """Minimal recovery hook for certificate-backed Shield failures."""
        del launch
        self._show_error(f"Shield recovery required for {err.login}")
        self._set_panel_status("")
        card.set_launch_enabled(True)

    def _on_server_shield_recovery(self, login: str) -> None:
        def route_recovery() -> None:
            card = self._find_card(login)
            if card is None:
                self._show_error(f"Shield recovery required for {login}")
                return
            self._handle_shield_recovery(
                ShieldRecoveryRequired(login),
                self._current_launch_fn(),
                card,
            )

        QTimer.singleShot(0, route_recovery)

    def _show_shield_code_dialog(
        self,
        err: ShieldRequired,
        api_key: str,
        launch: Callable,
        card: AccountCard,
    ) -> None:
        dialog = ShieldCodeDialog(
            err.login,
            parent=self,
            message=(
                f"A security code was sent to the email for {err.login}.\n"
                "Enter the code below to verify this device."
            ),
        )
        if dialog.exec() != QDialog.DialogCode.Accepted:
            card.set_launch_enabled(True)
            return

        code = dialog.get_code()
        if not code:
            card.set_launch_enabled(True)
            return

        def validate_and_launch(on_progress: Callable) -> int:
            on_progress("Validating security code...")
            cert_data = validate_security_code(api_key, code)
            logger.info("[SHIELD] ValidateCode success")
            on_progress("Storing certificate...")
            store_shield_certificate(err.login, cert_data)
            on_progress("Shield validated, launching...")
            self._proxy_store.save_validated(err.login, err.proxy_url)
            return launch(
                err.login,
                None,
                err.proxy_url,
                on_progress=on_progress,
            )

        def on_success(result: object) -> None:
            self._show_success(f"Game launch for {err.login}")
            self._set_panel_status("")
            card.set_running(int(result))  # type: ignore[arg-type]

        def on_error(retry_err: object) -> None:
            self._show_error(str(retry_err))
            self._set_panel_status("")
            card.set_launch_enabled(True)

        run_in_background(
            validate_and_launch,
            on_success=on_success,
            on_error=on_error,
            on_progress=self._set_panel_status,
            parent=self,
        )

    def _check_shield(
        self,
        login: str,
        proxy_url: str,
        on_progress: Callable[[str], None] | None,
    ) -> None:
        """Check if proxy IP needs Shield verification. Raises ShieldRequired if so.

        If a certificate already exists locally, skip entirely — certificates are
        machine-bound (hm1/hm2), not IP-bound. CreateToken will include the
        certificate_hash which authorizes the request regardless of proxy IP.

        Shield enrollment only needed when no certificate exists AND account
        security requires it.
        """
        try:
            CryptoHelper.getStoredCertificate(login)
            logger.info(
                f"[SHIELD] Certificate exists for {login}, skipping Shield check"
            )
            return
        except FileNotFoundError:
            pass

        if on_progress:
            on_progress("Checking proxy authorization...")
        api_key = CryptoHelper.getStoredApiKey(login)["apikey"]["key"]
        if check_proxy_needs_shield(api_key, proxy_url):
            raise ShieldRequired(login, proxy_url)

    def _launch_dofus(
        self,
        login: str,
        interface_ip: str | None,
        proxy_url: str | None,
        on_progress: Callable[[str], None] | None = None,
    ) -> int:
        proxy_listener, proxy_url = build_proxy_listener(proxy_url)
        if proxy_url:
            interface_ip = None
            if on_progress:
                on_progress("Verifying proxy...")
            verify_proxy_ip(proxy_url)
            self._check_shield(login, proxy_url, on_progress)
        return self._server.launch_dofus(
            login,
            proxy_listener=proxy_listener,
            proxy_url=proxy_url,
            interface_ip=interface_ip,
            on_progress=on_progress,
        )

    def _launch_retro(
        self,
        login: str,
        interface_ip: str | None,
        proxy_url: str | None,
        on_progress: Callable[[str], None] | None = None,
    ) -> int:
        if proxy_url:
            interface_ip = None
            if on_progress:
                on_progress("Verifying proxy...")
            verify_proxy_ip(proxy_url)
            self._check_shield(login, proxy_url, on_progress)
        return self._server.launch_retro(
            login,
            proxy_url=proxy_url,
            interface_ip=interface_ip,
            on_progress=on_progress,
        )

    # --- Account removal ---

    def _on_remove_account(self, login: str, card: AccountCard) -> None:
        if card.is_running:
            self._show_error("Stop the game before removing")
            return

        reply = QMessageBox.question(
            self,
            "Remove Account",
            f"Remove {login}?\nThis deletes the API key and certificate.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        def task(_on_progress: object) -> None:
            try:
                stored = CryptoHelper.getStoredApiKey(login)
                api_key = stored["apikey"]["key"]
            except StopIteration:
                api_key = None
            remove_account(login, api_key)

        def on_success(_result: object) -> None:
            self._proxy_store.assign_proxy(login, None)
            self._card_layout.removeWidget(card)
            card.hide()
            card.deleteLater()
            self._cards.remove(card)
            self._accounts = [
                a for a in self._accounts if a["apikey"]["login"] != login
            ]
            self._sync_empty_state()
            self._show_success(f"Removed {login}")

        def on_error(err: object) -> None:
            self._show_error(f"Remove failed: {err}")

        run_in_background(task, on_success=on_success, on_error=on_error, parent=self)

    # --- Dialogs ---

    def _open_proxy_dialog(self) -> None:
        dialog = ProxyDialog(self._proxy_store, parent=self)
        dialog.exec()
        for card in self._cards:
            card.update_proxies()

    def _open_add_account_dialog(self) -> None:
        from ankama_launcher_emulator.gui.add_account_dialog import AddAccountDialog

        dialog = AddAccountDialog(self._proxy_store, parent=self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self._schedule_refresh()

    # --- Info bars ---

    def _show_success(self, msg: str) -> None:
        InfoBar.success(
            "", msg, duration=3000, position=InfoBarPosition.TOP_RIGHT, parent=self
        )

    def _show_error(self, msg: str) -> None:
        InfoBar.error(
            "", msg, duration=6000, position=InfoBarPosition.TOP_RIGHT, parent=self
        )

    # --- Refresh timer ---

    def _start_refresh_timer(self) -> None:
        self._refresh_timer = QTimer(self)
        self._refresh_timer.setInterval(10_000)
        self._refresh_timer.timeout.connect(self._schedule_refresh)
        self._refresh_timer.start()

    def _schedule_refresh(self) -> None:
        if self._is_refreshing:
            return
        self._is_refreshing = True

        def fetch(_on_progress: Callable) -> tuple:
            return CryptoHelper.getStoredApiKeys(), get_available_network_interfaces()

        def on_success(result: object) -> None:
            accounts, interfaces = cast(tuple, result)
            self._apply_refresh(accounts, interfaces)

        run_in_background(
            fetch,
            on_success=on_success,
            on_error=lambda _: setattr(self, "_is_refreshing", False),
            parent=self,
        )

    def _apply_refresh(
        self, new_accounts: list, new_interfaces: dict[str, tuple[str, str]]
    ) -> None:
        self._is_refreshing = False

        current_logins: set[str] = {acc["apikey"]["login"] for acc in self._accounts}
        new_logins: set[str] = {acc["apikey"]["login"] for acc in new_accounts}

        if current_logins != new_logins:
            for account in new_accounts:
                login = account["apikey"]["login"]
                if login not in current_logins:
                    self._add_card(account, new_interfaces)

            for login in current_logins - new_logins:
                for card in self._cards[:]:
                    if card.login == login and not card.is_running:
                        self._card_layout.removeWidget(card)
                        card.hide()
                        card.deleteLater()
                        self._cards.remove(card)

            self._accounts = new_accounts
            self._sync_empty_state()

        if new_interfaces != self._interfaces:
            for card in self._cards:
                card.update_interfaces(new_interfaces)
            self._interfaces = new_interfaces
