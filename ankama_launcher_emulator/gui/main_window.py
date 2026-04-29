import logging
import importlib
from typing import Callable, cast

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QColor, QPixmap
from PyQt6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
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
    ScrollArea,
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
    ORANGE_HOVER_HEXA,
    PANEL_ALT_HEXA,
    PANEL_BG_HEXA,
    RED_HEXA,
    TEXT_DIM_HEXA,
    SCROLLBAR_HEXA,
    TEXT_HEXA,
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
from ankama_launcher_emulator.haapi.account_meta import AccountMeta
from ankama_launcher_emulator.haapi.account_persistence import (
    persist_managed_account,
)
from ankama_launcher_emulator.haapi.portable_exchange import (
    export_portable_account,
    import_portable_account,
)
from ankama_launcher_emulator.haapi.pkce_auth import ZaapPkceSession
from ankama_launcher_emulator.haapi.shield import (
    request_security_code,
    store_shield_certificate,
    validate_security_code,
)
from ankama_launcher_emulator.server.server import AnkamaLauncherServer
from ankama_launcher_emulator.utils.app_config import (
    get_last_selected_game,
    set_last_selected_game,
)
from ankama_launcher_emulator.utils.internet import get_available_network_interfaces
from ankama_launcher_emulator.utils.proxy import build_proxy_listener, verify_proxy_ip
from ankama_launcher_emulator.utils.proxy_store import ProxyStore

logger = logging.getLogger()


def _load_embedded_auth_dialog_class():
    module = importlib.import_module(
        "ankama_launcher_emulator.gui.embedded_auth_browser_dialog"
    )
    return module.EmbeddedAuthBrowserDialog


def _is_unauthorized(err: object) -> bool:
    resp = getattr(err, "response", None)
    return getattr(resp, "status_code", None) == 401


class MainWindow(QMainWindow):
    def __init__(
        self,
        server: AnkamaLauncherServer,
        accounts: list,
        all_interface: dict[str, tuple[str, str]],
        *,
        bootstrap_loading: bool = False,
    ):
        super().__init__()
        self._server = server
        self._accounts: list = accounts
        self._interfaces: dict[str, tuple[str, str]] = all_interface
        self._proxy_store = ProxyStore()
        self._cards: list[AccountCard] = []
        self._launch_contexts: dict[str, dict[str, object]] = {}
        self._current_game_is_dofus3: bool = self._load_initial_game_selection()
        self._is_refreshing_accounts = False
        self._is_refreshing_interfaces = False
        self._refresh_generation = 0
        self._bootstrap_loading = bootstrap_loading
        self._bootstrap_accounts_done = not bootstrap_loading
        self._bootstrap_interfaces_done = not bootstrap_loading
        server_handler = getattr(self._server, "handler", None)
        if server_handler is not None:
            server_handler.on_shield_recovery = self._on_server_shield_recovery
            server_handler.on_session_expired = self._on_server_session_expired
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
            f"CardWidget#warningCard {{ background-color: {PANEL_ALT_HEXA}; border: 1px solid {BORDER_HEXA}; border-radius: 16px; }}"
            f"CardWidget#warningCard BodyLabel {{ color: {TEXT_DIM_HEXA}; }}"
            f"CardWidget#warningCard CaptionLabel {{ color: {TEXT_MUTED_HEXA}; }}"
            f"CardWidget#emptyStateCard {{ background-color: {PANEL_BG_HEXA}; border: 1px solid {BORDER_HEXA}; border-radius: 20px; }}"
            f"CardWidget#emptyStateCard BodyLabel {{ color: {TEXT_MUTED_HEXA}; }}"
            f"QScrollArea {{ background-color: {APP_BG_HEXA}; border: none; }}"
            f"QScrollArea > QWidget > QWidget {{ background-color: {APP_BG_HEXA}; }}"
            f"QWidget#cardContainer {{ background-color: {APP_BG_HEXA}; }}"
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

        header_row = QHBoxLayout()
        header_row.setSpacing(14)

        self._top_bar = QWidget()
        self._top_bar.setObjectName("topBar")
        self._top_bar.setMinimumWidth(420)
        top_bar_layout = QVBoxLayout(self._top_bar)
        top_bar_layout.setContentsMargins(20, 18, 20, 18)
        top_bar_layout.setSpacing(12)

        selected_game_row = QHBoxLayout()
        selected_game_row.setSpacing(16)

        self._selected_game_logo = QLabel()
        self._selected_game_logo.setFixedSize(112, 86)
        selected_game_row.addWidget(
            self._selected_game_logo, alignment=Qt.AlignmentFlag.AlignCenter
        )

        title_stack = QVBoxLayout()
        title_stack.setSpacing(2)
        title_stack.addStretch()

        top_label = CaptionLabel("Selected Game")
        self._title_label = TitleLabel(
            DOFUS_3_TITLE if self._current_game_is_dofus3 else DOFUS_RETRO_TITLE
        )
        self._title_label.setAlignment(Qt.AlignmentFlag.AlignLeft)

        title_stack.addWidget(top_label)
        title_stack.addWidget(self._title_label)
        title_stack.addStretch()
        selected_game_row.addLayout(title_stack, 1)
        top_bar_layout.addLayout(selected_game_row)

        self._banner = DownloadBanner(self._top_bar)
        top_bar_layout.addWidget(self._banner)

        if not CYTRUS_INSTALLED:
            self._warning_card = CardWidget()
            self._warning_card.setObjectName("warningCard")
            warning_layout = QVBoxLayout(self._warning_card)
            warning_layout.setContentsMargins(12, 10, 12, 10)
            warning_layout.setSpacing(4)
            warning_layout.addWidget(BodyLabel("cytrus-v6 is not installed"))
            warning_hint = CaptionLabel(
                "Auto-update will not work. Install it with: npm install -g cytrus-v6"
            )
            warning_hint.setWordWrap(True)
            warning_layout.addWidget(warning_hint)
            top_bar_layout.addWidget(self._warning_card)
        else:
            self._warning_card = None

        header_row.addWidget(self._top_bar, 1)
        header_row.addStretch(1)
        layout.addLayout(header_row)

        if not has_shown_star_repo():
            layout.addWidget(StarBar())

        action_row = QHBoxLayout()
        action_row.setSpacing(10)
        action_row.addStretch()

        gear_btn = PushButton("Proxies")
        gear_btn.setFixedWidth(100)
        gear_btn.setFixedHeight(28)
        gear_btn.setStyleSheet(
            "PushButton {"
            f"background-color: {PANEL_ALT_HEXA};"
            f"border: 1px solid {BORDER_HEXA};"
            "border-radius: 14px;"
            "padding: 2px 10px;"
            "}"
        )
        gear_btn.clicked.connect(self._open_proxy_dialog)
        action_row.addWidget(gear_btn)

        import_btn = PushButton("Import")
        import_btn.setFixedWidth(100)
        import_btn.setFixedHeight(28)
        import_btn.setStyleSheet(gear_btn.styleSheet())
        import_btn.clicked.connect(self._open_import_account_dialog)
        action_row.addWidget(import_btn)

        add_btn = PushButton("Add Account")
        add_btn.setFixedWidth(124)
        add_btn.setFixedHeight(28)
        add_btn.setStyleSheet(
            "PushButton {"
            f"background-color: {ORANGE_HEXA};"
            f"color: {TEXT_HEXA};"
            "border: none;"
            "border-radius: 14px;"
            "padding: 2px 10px;"
            "}"
            "PushButton:hover {"
            f"background-color: {ORANGE_HOVER_HEXA};"
            "}"
        )
        add_btn.clicked.connect(self._open_add_account_dialog)
        action_row.addWidget(add_btn)
        layout.addLayout(action_row)

        self._accounts_scroll = ScrollArea()
        self._accounts_scroll.setWidgetResizable(True)
        vbar = self._accounts_scroll.scrollDelagate.vScrollBar  # type: ignore[attr-defined]
        vbar.darkBackgroundColor = QColor(SCROLLBAR_HEXA)  # type: ignore[attr-defined]

        self._card_container = QWidget()
        self._card_container.setObjectName("cardContainer")
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
        self._accounts_scroll.setWidget(self._card_container)
        layout.addWidget(self._accounts_scroll, 1)

        self._select_game(self._current_game_is_dofus3, persist=False)
        self._sync_empty_state()

    def _load_initial_game_selection(self) -> bool:
        saved_game = get_last_selected_game()
        if saved_game == "dofus3" and DOFUS_INSTALLED:
            return True
        if saved_game == "retro" and RETRO_INSTALLED:
            return False
        return DOFUS_INSTALLED or not RETRO_INSTALLED

    def _select_game(self, is_dofus_3: bool, *, persist: bool = True) -> None:
        self._current_game_is_dofus3 = is_dofus_3
        title = DOFUS_3_TITLE if is_dofus_3 else DOFUS_RETRO_TITLE
        logo_path = RESOURCES / ("Dofus3.png" if is_dofus_3 else "DofusRetro.png")
        self._title_label.setText(title)
        self._selected_game_logo.setPixmap(
            QPixmap(str(logo_path)).scaled(
                112,
                86,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
        )
        self._dofus_selector.set_active(is_dofus_3)
        self._retro_selector.set_active(not is_dofus_3)
        if persist:
            set_last_selected_game("dofus3" if is_dofus_3 else "retro")

    def _current_launch_fn(self) -> Callable:
        if self._current_game_is_dofus3:
            return self._launch_dofus
        return self._launch_retro

    def _add_card(self, account: dict, all_interface: dict) -> AccountCard:
        login = account["apikey"]["login"]
        is_official = bool(account.get("is_official", False))
        card = AccountCard(
            login, all_interface, self._proxy_store, self._card_container,
            is_official=is_official,
        )
        self._cards.append(card)
        card.launch_requested.connect(self._make_launch_handler(login, card))
        card.export_requested.connect(self._open_export_account_dialog)
        card.remove_requested.connect(
            lambda l=login, c=card: self._on_remove_account(l, c)
        )
        card.error_occurred.connect(self._show_error)
        card.reconnect_requested.connect(self._handle_reconnect)
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

    def start_initial_refresh(self) -> None:
        QTimer.singleShot(0, self._schedule_refresh)

    def _next_refresh_generation(self) -> int:
        self._refresh_generation += 1
        return self._refresh_generation

    def _finish_bootstrap_accounts(self) -> None:
        self._bootstrap_accounts_done = True
        self._bootstrap_loading = False
        self._sync_empty_state()

    def _finish_bootstrap_interfaces(self) -> None:
        self._bootstrap_interfaces_done = True

    def _update_empty_state_message(self) -> None:
        if self._bootstrap_loading:
            self._empty_state_label.setText(
                "Loading accounts and network interfaces...\n"
                "The launcher shell is ready; account data will appear shortly."
            )
            self._empty_state_label.setStyleSheet(f"color: {TEXT_MUTED_HEXA};")
            return
        self._empty_state_label.setText(
            "No account found.\n"
            "Check that Ankama Launcher is installed and has logged accounts.\n"
            f"Expected path: {ZAAP_PATH}/keydata/\n\n"
            "Or click 'Add Account' to add an account manually."
        )
        self._empty_state_label.setStyleSheet(f"color: {RED_HEXA};")

    def _sync_empty_state(self) -> None:
        self._update_empty_state_message()
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
            interface_ip = cast(str | None, iface)
            portable = bool((AccountMeta().get(login) or {}).get("portable_mode"))
            self._launch_contexts[login] = {
                "launch": launch,
                "card": card,
                "interface_ip": interface_ip,
                "proxy_url": proxy_url,
                "portable": portable,
            }

            if AccountMeta().cert_proxy_changed(login, proxy_url):
                logger.info(f"[LAUNCH] Proxy changed since cert validation for {login}, triggering shield refresh")
                self._handle_shield_light(login, launch, card)
                return

            def on_success(result: object) -> None:
                self._show_success(f"Game launch for {login}")
                self._set_panel_status("")
                card.set_running(int(result))  # type: ignore[arg-type]
                AccountMeta().record_launch_state(
                    login, portable, proxy_url, interface_ip
                )

            def on_error(err: object) -> None:
                self._show_error(str(err))
                self._set_panel_status("")
                card.set_launch_enabled(True)

            run_in_background(
                lambda on_progress: launch(
                    login,
                    interface_ip,
                    proxy_url,
                    on_progress=on_progress,
                ),
                on_success=on_success,
                on_error=on_error,
                on_progress=self._set_panel_status,
                parent=self,
            )

        return handler

    def _handle_shield_light(
        self,
        login: str,
        launch: Callable,
        card: AccountCard,
    ) -> None:
        """Email-only Shield flow using the stored API key.

        Triggered by ShieldRecoveryRequired (403 at CreateToken). If the
        SecurityCode or ValidateCode call returns 401, escalates to the
        heavy (PKCE+email) path.
        """
        context = self._launch_contexts.get(login, {})
        proxy_url = cast(str | None, context.get("proxy_url"))
        interface_ip = cast(str | None, context.get("interface_ip"))

        if card.is_running:
            card.stop_process()
        card.set_launch_enabled(False)
        self._set_panel_status("Requesting Shield code via email...")

        def request_code(on_progress: Callable) -> str:
            uuid_active, _, key_folder, _, _ = CryptoHelper.get_crypto_context(login)
            api_key = CryptoHelper.getStoredApiKey(login, key_folder, uuid_active)[
                "apikey"
            ]["key"]
            on_progress("Requesting security code via email...")
            request_security_code(api_key, proxy_url=proxy_url)
            logger.info("[SHIELD] Security code requested via email")
            return api_key

        def on_code_requested(result: object) -> None:
            api_key = str(result)
            self._set_panel_status("")
            self._show_shield_code_dialog(
                login, api_key, launch, card, proxy_url, interface_ip
            )

        def on_error(exc: object) -> None:
            if _is_unauthorized(exc):
                logger.info(
                    f"[SHIELD] Light 401 on SecurityCode for {login}, escalating"
                )
                self._handle_shield_heavy(login, launch, card)
                return
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

    def _handle_shield_heavy(
        self,
        login: str,
        launch: Callable,
        card: AccountCard,
    ) -> None:
        """Full PKCE + email Shield flow. Triggered by SessionExpired (401)
        or escalation from the light path on 401."""
        self._set_panel_status("Stored session rejected, re-authentication required...")
        if card.is_running:
            card.stop_process()
        card.set_launch_enabled(False)
        try:
            dialog_class = _load_embedded_auth_dialog_class()
            session = ZaapPkceSession()
            dialog = dialog_class(
                session.auth_url, login, session.code_verifier, parent=self
            )
        except (ImportError, RuntimeError, OSError) as exc:
            self._show_error(f"Embedded auth dialog unavailable: {exc}")
            self._set_panel_status("")
            card.set_launch_enabled(True)
            return

        if dialog.exec() != QDialog.DialogCode.Accepted:
            self._set_panel_status("")
            card.set_launch_enabled(True)
            return

        tokens = dialog.get_tokens()
        if not tokens:
            err = dialog.get_token_error() or "Token exchange failed"
            self._show_error(f"Re-authentication failed: {err}")
            self._set_panel_status("")
            card.set_launch_enabled(True)
            return

        def reauthenticate(on_progress: Callable[[str], None]) -> dict:
            on_progress("Signing in again...")
            from ankama_launcher_emulator.haapi.pkce_auth import fetch_account_profile

            account = fetch_account_profile(tokens["access_token"])
            if not account.get("id"):
                raise RuntimeError("Failed to get account info")
            data = {
                "access_token": tokens["access_token"],
                "refresh_token": tokens.get("refresh_token"),
                "account_id": account["id"],
                "login": account.get("login", login),
                "nickname": account.get("nickname", ""),
                "security": account.get("security", []),
            }
            on_progress("Requesting security code via email...")
            proxy_url = cast(
                str | None,
                self._launch_contexts.get(login, {}).get("proxy_url")
                or (AccountMeta().get(login) or {}).get("proxy_url"),
            )
            request_security_code(data["access_token"], proxy_url=proxy_url)
            data["proxy_url"] = proxy_url
            return data

        def on_reauthenticated(result: object) -> None:
            self._set_panel_status("")
            data = dict(result)  # type: ignore[arg-type]
            self._show_shield_recovery_dialog(login, data, launch, card)

        def on_error(exc: object) -> None:
            self._show_error(f"Shield recovery failed: {exc}")
            self._set_panel_status("")
            card.set_launch_enabled(True)

        run_in_background(
            reauthenticate,
            on_success=on_reauthenticated,
            on_error=on_error,
            on_progress=self._set_panel_status,
            parent=self,
        )

    def _on_server_shield_recovery(self, login: str) -> None:
        def route_recovery() -> None:
            context = self._launch_contexts.get(login)
            launch = cast(Callable | None, context.get("launch")) if context else None
            card = cast(AccountCard | None, context.get("card")) if context else None
            if launch is None:
                launch = self._current_launch_fn()
            if card is None:
                card = self._find_card(login)
            if card is None:
                self._show_error(f"Shield recovery required for {login}")
                return
            self._handle_shield_light(login, launch, card)

        QTimer.singleShot(0, route_recovery)

    def _on_server_session_expired(self, login: str) -> None:
        def route_expired() -> None:
            context = self._launch_contexts.get(login)
            launch = cast(Callable | None, context.get("launch")) if context else None
            card = cast(AccountCard | None, context.get("card")) if context else None
            if launch is None:
                launch = self._current_launch_fn()
            if card is None:
                card = self._find_card(login)
            if card is None:
                self._show_error(f"Session expired for {login}")
                return
            self._handle_shield_heavy(login, launch, card)

        QTimer.singleShot(0, route_expired)

    def _handle_reconnect(self, login: str) -> None:
        from ankama_launcher_emulator.gui.add_account_dialog import AddAccountDialog

        card = self._find_card(login)
        if card is None:
            return

        meta_entry = AccountMeta().get(login) or {}
        initial_alias = cast(str | None, meta_entry.get("alias"))
        initial_proxy_id = self._proxy_store.get_assignment(login)

        dialog = AddAccountDialog(
            self._proxy_store,
            parent=self,
            locked_login=login,
            initial_proxy_id=initial_proxy_id,
            initial_alias=initial_alias,
        )

        def _on_finished(_result: int) -> None:
            card.refresh_launch_button()
            self._schedule_refresh()
            dialog.deleteLater()

        dialog.finished.connect(_on_finished)
        dialog.show()

    def _show_shield_recovery_dialog(
        self,
        login: str,
        data: dict,
        launch: Callable,
        card: AccountCard,
    ) -> None:
        dialog = ShieldCodeDialog(
            login,
            parent=self,
            message=(
                f"A security code was sent to the email for {login}.\n"
                "Enter the code below to authorize this connection again."
            ),
        )
        if dialog.exec() != QDialog.DialogCode.Accepted:
            card.set_launch_enabled(True)
            return

        code = dialog.get_code()
        if not code:
            card.set_launch_enabled(True)
            return

        context = self._launch_contexts.get(login, {})
        interface_ip = cast(str | None, context.get("interface_ip"))
        proxy_url = cast(str | None, context.get("proxy_url"))

        def validate_and_launch(on_progress: Callable[[str], None]) -> int:
            on_progress("Validating security code...")
            uuid_active, cert_folder, _, hm1, hm2 = CryptoHelper.get_crypto_context(
                login
            )
            cert_data = validate_security_code(
                data["access_token"], code, hm1=hm1, hm2=hm2, proxy_url=proxy_url
            )
            on_progress("Storing refreshed certificate...")
            store_shield_certificate(login, cert_data, cert_folder, uuid_active)
            AccountMeta().record_cert_validated(login, proxy_url)
            alias = cast(str | None, (AccountMeta().get(login) or {}).get("alias"))
            if alias is None:
                alias = cast(str | None, data.get("nickname")) or None
            persist_managed_account(
                login,
                data["account_id"],
                data["access_token"],
                data.get("refresh_token"),
                alias=alias,
                hm1=None,
            )
            if proxy_url:
                self._proxy_store.save_validated(login, proxy_url)
            on_progress("Retrying launch...")
            return launch(
                login,
                interface_ip,
                proxy_url,
                on_progress=on_progress,
            )

        def on_success(result: object) -> None:
            self._show_success(f"Game launch for {login}")
            self._set_panel_status("")
            card.set_running(int(result))  # type: ignore[arg-type]
            portable = bool((AccountMeta().get(login) or {}).get("portable_mode"))
            AccountMeta().record_launch_state(login, portable, proxy_url, interface_ip)

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

    def _show_shield_code_dialog(
        self,
        login: str,
        api_key: str,
        launch: Callable,
        card: AccountCard,
        proxy_url: str | None,
        interface_ip: str | None,
    ) -> None:
        dialog = ShieldCodeDialog(
            login,
            parent=self,
            message=(
                f"A security code was sent to the email for {login}.\n"
                "Enter the code below to verify this device."
            ),
        )

        def _do_resend(_on_progress: object) -> None:
            request_security_code(api_key, proxy_url=proxy_url)

        def _on_resend_success(_result: object) -> None:
            dialog.resend_done(success=True)

        def _on_resend_error(_err: object) -> None:
            dialog.resend_done(success=False)

        dialog.resend_requested.connect(
            lambda: run_in_background(
                _do_resend,
                on_success=_on_resend_success,
                on_error=_on_resend_error,
                parent=self,
            )
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
            uuid_active, cert_folder, _, hm1, hm2 = CryptoHelper.get_crypto_context(
                login
            )
            cert_data = validate_security_code(
                api_key, code, hm1=hm1, hm2=hm2, proxy_url=proxy_url
            )
            logger.info("[SHIELD] ValidateCode success")
            on_progress("Storing certificate...")
            store_shield_certificate(login, cert_data, cert_folder, uuid_active)
            AccountMeta().record_cert_validated(login, proxy_url)
            if proxy_url:
                self._proxy_store.save_validated(login, proxy_url)
            on_progress("Shield validated, launching...")
            return launch(
                login,
                interface_ip,
                proxy_url,
                on_progress=on_progress,
            )

        def on_success(result: object) -> None:
            self._show_success(f"Game launch for {login}")
            self._set_panel_status("")
            card.set_running(int(result))  # type: ignore[arg-type]
            portable = bool((AccountMeta().get(login) or {}).get("portable_mode"))
            AccountMeta().record_launch_state(login, portable, proxy_url, interface_ip)

        def on_error(retry_err: object) -> None:
            if _is_unauthorized(retry_err):
                logger.info(
                    f"[SHIELD] Light 401 on ValidateCode for {login}, escalating"
                )
                self._handle_shield_heavy(login, launch, card)
                return
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
        if AccountMeta().get(login) is None:
            self._show_error("Cannot remove accounts managed by the official launcher.")
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
                uuid_active, _, key_folder, _, _ = CryptoHelper.get_crypto_context(
                    login
                )
                stored = CryptoHelper.getStoredApiKey(login, key_folder, uuid_active)
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

        def _on_finished(_result: int) -> None:
            self._schedule_refresh()
            dialog.deleteLater()

        dialog.finished.connect(_on_finished)
        dialog.show()

    def _open_export_account_dialog(self, login: str | None = None) -> None:
        from ankama_launcher_emulator.gui.portable_account_dialogs import (
            PortableAccountExportDialog,
        )

        meta = AccountMeta()
        if not login:
            self._show_error("Select a portable account to export.")
            return
        entry = meta.get(login)
        if entry is None:
            self._show_error("Only managed accounts can be exported.")
            return
        if not entry.get("portable_mode"):
            self._show_error("Enable portable mode before exporting this account.")
            return
        uuid_active, cert_folder, _, _, _ = CryptoHelper.get_crypto_context(login)
        has_certificate = True
        try:
            CryptoHelper.getStoredCertificate(login, cert_folder, uuid_active)
        except (FileNotFoundError, OSError):
            has_certificate = False

        dialog = PortableAccountExportDialog(
            login=login,
            alias=cast(str | None, entry.get("alias")),
            has_proxy=bool(self._proxy_store.get_proxy_url(login)),
            has_certificate=has_certificate,
            parent=self,
        )
        if dialog.exec() != QDialog.DialogCode.Accepted:
            dialog.deleteLater()
            return

        output_path = dialog.output_path()
        passphrase = dialog.passphrase()
        dialog.deleteLater()
        self._set_panel_status("Exporting portable account...")

        def task(_on_progress: Callable) -> str:
            return export_portable_account(
                login, passphrase, output_path, self._proxy_store
            )

        def on_success(result: object) -> None:
            self._set_panel_status("")
            self._show_success(f"Exported {result}")

        def on_error(err: object) -> None:
            self._set_panel_status("")
            self._show_error(str(err))

        run_in_background(task, on_success=on_success, on_error=on_error, parent=self)

    def _open_import_account_dialog(self) -> None:
        from ankama_launcher_emulator.gui.portable_account_dialogs import (
            PortableAccountImportDialog,
        )

        dialog = PortableAccountImportDialog(parent=self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            dialog.deleteLater()
            return

        input_path = dialog.input_path()
        passphrase = dialog.passphrase()
        dialog.deleteLater()
        self._set_panel_status("Importing portable account...")

        def task(_on_progress: Callable) -> str:
            return import_portable_account(
                input_path, passphrase, self._proxy_store
            )

        def on_success(result: object) -> None:
            self._set_panel_status("")
            for card in self._cards:
                card.update_proxies()
            self._schedule_refresh()
            self._show_success(f"Imported {result}")

        def on_error(err: object) -> None:
            self._set_panel_status("")
            self._show_error(str(err))

        run_in_background(task, on_success=on_success, on_error=on_error, parent=self)

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
        generation = self._next_refresh_generation()
        self._schedule_accounts_refresh(generation)
        self._schedule_interfaces_refresh(generation)

    def _schedule_accounts_refresh(self, generation: int) -> None:
        if self._is_refreshing_accounts:
            return
        self._is_refreshing_accounts = True

        def fetch_accounts(_on_progress: Callable) -> list:
            from ankama_launcher_emulator.haapi.account_persistence import (
                list_all_api_keys,
            )

            return list_all_api_keys()

        def on_success(result: object) -> None:
            self._apply_accounts_refresh(cast(list, result), generation)

        def on_error(_: object) -> None:
            self._is_refreshing_accounts = False
            if not self._bootstrap_accounts_done:
                self._finish_bootstrap_accounts()

        run_in_background(
            fetch_accounts,
            on_success=on_success,
            on_error=on_error,
            parent=self,
        )

    def _schedule_interfaces_refresh(self, generation: int) -> None:
        if self._is_refreshing_interfaces:
            return
        self._is_refreshing_interfaces = True

        def fetch_interfaces(_on_progress: Callable) -> dict[str, tuple[str, str]]:
            return get_available_network_interfaces()

        def on_success(result: object) -> None:
            self._apply_interfaces_refresh(
                cast(dict[str, tuple[str, str]], result), generation
            )

        def on_error(_: object) -> None:
            self._is_refreshing_interfaces = False
            if not self._bootstrap_interfaces_done:
                self._finish_bootstrap_interfaces()

        run_in_background(
            fetch_interfaces,
            on_success=on_success,
            on_error=on_error,
            parent=self,
        )

    def _apply_accounts_refresh(self, new_accounts: list, generation: int) -> None:
        self._is_refreshing_accounts = False
        if generation != self._refresh_generation:
            return

        current_logins: set[str] = {acc["apikey"]["login"] for acc in self._accounts}
        new_logins: set[str] = {acc["apikey"]["login"] for acc in new_accounts}

        if current_logins != new_logins:
            for account in new_accounts:
                login = account["apikey"]["login"]
                if login not in current_logins:
                    self._add_card(account, self._interfaces)

            for login in current_logins - new_logins:
                for card in self._cards[:]:
                    if card.login == login and not card.is_running:
                        self._card_layout.removeWidget(card)
                        card.hide()
                        card.deleteLater()
                        self._cards.remove(card)

            self._accounts = new_accounts
        self._finish_bootstrap_accounts()

    def _apply_interfaces_refresh(
        self, new_interfaces: dict[str, tuple[str, str]], generation: int
    ) -> None:
        self._is_refreshing_interfaces = False
        if generation != self._refresh_generation:
            return
        if new_interfaces != self._interfaces:
            self._interfaces = new_interfaces
            for card in self._cards:
                card.update_interfaces(self._interfaces)
        if not self._bootstrap_interfaces_done:
            self._finish_bootstrap_interfaces()
