import logging
from typing import Callable, cast

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtWidgets import (
    QDialog,
    QFrame,
    QHBoxLayout,
    QMainWindow,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)
from qfluentwidgets import (
    BodyLabel,
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
    DOFUS_3_TITLE,
    DOFUS_RETRO_TITLE,
    ORANGE_HEXA,
    RED_HEXA,
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
from ankama_launcher_emulator.haapi.shield import (
    ShieldRequired,
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
        self._setup_ui(accounts, all_interface)
        self._start_refresh_timer()

    def _setup_ui(self, accounts: list, all_interface: dict) -> None:
        self.setWindowTitle("Ankama Launcher")
        self.setMinimumWidth(1000)
        self.resize(1150, 600)

        central = QWidget()
        self.setCentralWidget(central)

        layout = QVBoxLayout(central)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(12)

        if not has_shown_star_repo():
            layout.addWidget(StarBar())

        # Header row: [Dofus 3] [Retro] ... [Gear] [+ Add]
        header_row = QHBoxLayout()
        header_row.setSpacing(12)

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

        header_row.addWidget(self._dofus_selector)
        header_row.addWidget(self._retro_selector)
        header_row.addStretch()

        gear_btn = PushButton("Proxies")
        gear_btn.setFixedWidth(80)
        gear_btn.clicked.connect(self._open_proxy_dialog)
        header_row.addWidget(gear_btn)

        add_btn = PushButton("+ Add")
        add_btn.setFixedWidth(80)
        add_btn.clicked.connect(self._open_add_account_dialog)
        header_row.addWidget(add_btn)

        layout.addLayout(header_row)

        if not CYTRUS_INSTALLED:
            cytrus_warning = BodyLabel(
                "cytrus-v6 is not installed. Auto-update will not work.\n"
                "Install it with: npm install -g cytrus-v6"
            )
            cytrus_warning.setStyleSheet(f"color: {ORANGE_HEXA};")
            cytrus_warning.setWordWrap(True)
            layout.addWidget(cytrus_warning)

        self._title_label = TitleLabel(
            DOFUS_3_TITLE if self._current_game_is_dofus3 else DOFUS_RETRO_TITLE
        )
        self._title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self._title_label)

        # Banner for status messages
        self._banner = DownloadBanner()
        layout.addWidget(self._banner)

        if not accounts:
            label = BodyLabel(
                f"No account found.\n"
                f"Check that ankama launcher is installed and has logged accounts.\n"
                f"Expected path : {ZAAP_PATH}/keydata/\n\n"
                f"Or click '+ Add' to add an account manually."
            )
            label.setStyleSheet(f"color: {RED_HEXA};")
            label.setWordWrap(True)
            layout.addWidget(label)
            self._no_account_label = label
        else:
            self._no_account_label = None

        # Single scroll area with all account cards
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)

        self._card_container = QWidget()
        self._card_layout = QVBoxLayout(self._card_container)
        self._card_layout.setContentsMargins(0, 0, 0, 0)
        self._card_layout.setSpacing(8)

        for account in accounts:
            self._add_card(account, all_interface)

        self._card_layout.addStretch()
        scroll.setWidget(self._card_container)
        layout.addWidget(scroll, 1)

        self._select_game(self._current_game_is_dofus3)

    def _select_game(self, is_dofus_3: bool) -> None:
        self._current_game_is_dofus3 = is_dofus_3
        self._title_label.setText(DOFUS_3_TITLE if is_dofus_3 else DOFUS_RETRO_TITLE)
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
        card.error_occurred.connect(self._show_error)
        self._card_layout.insertWidget(self._card_layout.count() - 1, card)
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
            # Hide no-account label if we now have accounts
            if self._no_account_label and new_accounts:
                self._no_account_label.hide()
                self._no_account_label = None

            # Add new accounts
            for account in new_accounts:
                login = account["apikey"]["login"]
                if login not in current_logins:
                    self._add_card(account, new_interfaces)

            # Remove departed accounts
            for login in current_logins - new_logins:
                for card in self._cards[:]:
                    if card.login == login and not card.is_running:
                        self._card_layout.removeWidget(card)
                        card.hide()
                        card.deleteLater()
                        self._cards.remove(card)

            self._accounts = new_accounts

        if new_interfaces != self._interfaces:
            for card in self._cards:
                card.update_interfaces(new_interfaces)
            self._interfaces = new_interfaces
