"""Interactive fake-backend GUI harness for macOS design checks.

This script intentionally reuses the production PyQt widgets while replacing
every backend-facing dependency with in-memory fakes. It does not start the
launcher server, call HAAPI, verify proxies, launch games, or write to the real
application config directory.

Usage:
    uv run python tests/debug_gui_demo.py
    uv run python tests/debug_gui_demo.py --offscreen --smoke
"""

from __future__ import annotations

import argparse
import contextlib
import io
import os
import sys
import tempfile
from contextlib import ExitStack
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, cast
from unittest.mock import patch

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

_CONFIG_HOME = tempfile.TemporaryDirectory(prefix="ankalt-gui-demo-")
os.environ["XDG_CONFIG_HOME"] = _CONFIG_HOME.name

DEMO_ACCOUNTS = [
    {"apikey": {"login": "ready.alt@example.com"}},
    {"apikey": {"login": "needs-reconnect@example.com"}},
    {"apikey": {"login": "proxy.alt@example.com"}},
    {"apikey": {"login": "shared-proxy@example.com"}},
]

DEMO_INTERFACES = {
    "192.168.1.24": ("Wi-Fi", "198.51.100.24"),
    "10.8.0.5": ("VPN", "203.0.113.5"),
    "172.16.12.2": ("USB Ethernet", "192.0.2.44"),
}

READY_LOGINS = {
    "ready.alt@example.com",
    "proxy.alt@example.com",
    "shared-proxy@example.com",
}

APP_BG = "#111111"
PANEL_BG = "#191919"
PANEL_ALT = "#202020"
BORDER = "#2b2b2b"
TEXT = "#ffffff"
TEXT_MUTED = "#737373"
ORANGE = "#d25f04"

DEMO_DARK_STYLESHEET = f"""
QWidget#demoControls, QDialog {{
    background-color: {APP_BG};
    color: {TEXT};
}}
AccountCard, CardWidget#demoAccountCard {{
    background-color: {PANEL_BG};
    border: 1px solid {BORDER};
    border-radius: 18px;
}}
CardWidget#demoAccountCard BodyLabel, CardWidget#demoAccountCard QLabel {{
    color: {TEXT};
}}
CardWidget#demoAccountCard CaptionLabel {{
    color: {TEXT_MUTED};
}}
CardWidget#demoAccountCard ComboBox, CardWidget#demoAccountCard PushButton,
CardWidget#demoAccountCard PrimaryPushButton {{
    background-color: {PANEL_ALT};
    color: {TEXT};
    border: 1px solid {BORDER};
    min-height: 28px;
    max-height: 28px;
    border-radius: 14px;
    padding: 2px 10px;
}}
QWidget#demoControls CardWidget, QDialog CardWidget {{
    background-color: {PANEL_BG};
    border: 1px solid {BORDER};
    border-radius: 12px;
}}
QWidget#demoControls BodyLabel, QWidget#demoControls QLabel,
QDialog BodyLabel, QDialog QLabel {{
    color: {TEXT};
}}
QWidget#demoControls CaptionLabel, QDialog CaptionLabel {{
    color: {TEXT_MUTED};
}}
QWidget#demoControls PushButton, QDialog PushButton,
QWidget#demoControls PrimaryPushButton, QDialog PrimaryPushButton {{
    background-color: {PANEL_ALT};
    color: {TEXT};
    border: 1px solid {BORDER};
    min-height: 28px;
    max-height: 28px;
    border-radius: 14px;
    padding: 2px 10px;
}}
QWidget#demoControls PushButton:hover, QDialog PushButton:hover,
QWidget#demoControls PrimaryPushButton:hover, QDialog PrimaryPushButton:hover {{
    border-color: {ORANGE};
}}
QDialog LineEdit, QDialog PasswordLineEdit, QDialog ComboBox,
QWidget#demoControls ComboBox {{
    background-color: {PANEL_ALT};
    color: {TEXT};
    border: 1px solid {BORDER};
    min-height: 28px;
    max-height: 28px;
    border-radius: 14px;
    padding: 2px 10px;
}}
"""


@dataclass
class _DemoProxyEntry:
    name: str
    url: str
    exit_ip: str | None = None
    tested_at: str | None = None


class _DemoProxyStore:
    _proxies: dict[str, _DemoProxyEntry] = {
        "paris": _DemoProxyEntry(
            "Paris SOCKS",
            "socks5://demo:demo@127.0.0.1:9050",
            "198.51.100.10",
        ),
        "montreal": _DemoProxyEntry(
            "Montreal HTTP",
            "http://demo:demo@127.0.0.1:8080",
            "203.0.113.40",
        ),
        "untested": _DemoProxyEntry(
            "Untested proxy",
            "socks5://demo:demo@127.0.0.1:9051",
            None,
        ),
    }
    _assignments: dict[str, str] = {
        "proxy.alt@example.com": "paris",
        "shared-proxy@example.com": "paris",
    }
    _counter = 0

    def list_proxies(self) -> dict[str, _DemoProxyEntry]:
        return dict(self._proxies)

    def add_proxy(self, name: str, url: str) -> str:
        self.__class__._counter += 1
        proxy_id = f"new-{self._counter}"
        self._proxies[proxy_id] = _DemoProxyEntry(name=name, url=url)
        return proxy_id

    def update_proxy(
        self,
        proxy_id: str,
        name: str | None = None,
        url: str | None = None,
        exit_ip: str | None = None,
        tested_at: str | None = None,
    ) -> None:
        entry = self._proxies.get(proxy_id)
        if entry is None:
            return
        if name is not None:
            entry.name = name
        if url is not None:
            entry.url = url
        if exit_ip is not None:
            entry.exit_ip = exit_ip
        if tested_at is not None:
            entry.tested_at = tested_at

    def remove_proxy(self, proxy_id: str) -> None:
        self._proxies.pop(proxy_id, None)
        self.__class__._assignments = {
            login: assigned
            for login, assigned in self._assignments.items()
            if assigned != proxy_id
        }

    def get_proxy(self, proxy_id: str) -> _DemoProxyEntry | None:
        return self._proxies.get(proxy_id)

    def assign_proxy(self, login: str, proxy_id: str | None) -> None:
        if proxy_id is None:
            self._assignments.pop(login, None)
            return
        self._assignments[login] = proxy_id

    def get_assignment(self, login: str) -> str | None:
        return self._assignments.get(login)

    def get_proxy_url(self, login: str) -> str | None:
        proxy_id = self.get_assignment(login)
        entry = self._proxies.get(proxy_id or "")
        return entry.url if entry else None

    def save_validated(
        self,
        login: str,
        proxy_url: str,
        exit_ip: str | None = None,
    ) -> None:
        for proxy_id, entry in self._proxies.items():
            if entry.url == proxy_url:
                entry.exit_ip = exit_ip or entry.exit_ip
                self._assignments[login] = proxy_id
                return
        proxy_id = self.add_proxy(proxy_url[:40], proxy_url)
        self._proxies[proxy_id].exit_ip = exit_ip
        self._assignments[login] = proxy_id

    def test_proxy(self, proxy_id: str) -> str | None:
        entry = self._proxies.get(proxy_id)
        if entry is None:
            return None
        entry.exit_ip = entry.exit_ip or "198.51.100.77"
        entry.tested_at = "demo"
        return entry.exit_ip


class _DemoAccountMeta:
    _data: dict[str, dict] = {
        "ready.alt@example.com": {
            "alias": "Cra",
            "portable_mode": True,
            "proxy_url": None,
        },
        "needs-reconnect@example.com": {
            "alias": "Reconnect case",
            "portable_mode": True,
            "proxy_url": None,
        },
        "proxy.alt@example.com": {
            "alias": "Proxy account",
            "portable_mode": False,
            "proxy_url": _DemoProxyStore._proxies["paris"].url,
        },
        "shared-proxy@example.com": {
            "alias": "In-use proxy",
            "portable_mode": False,
            "proxy_url": _DemoProxyStore._proxies["paris"].url,
        },
    }

    def get(self, login: str) -> dict | None:
        return self._data.get(login)

    def set_meta(
        self,
        login: str,
        source: str = "managed",
        alias: str | None = None,
    ) -> None:
        entry = self._data.setdefault(login, {})
        entry["source"] = source
        if alias is not None:
            entry["alias"] = alias

    def set_portable_mode(self, login: str, portable: bool) -> None:
        self._data.setdefault(login, {})["portable_mode"] = portable

    def set_proxy(self, login: str, proxy_url: str | None) -> None:
        self._data.setdefault(login, {})["proxy_url"] = proxy_url

    def record_launch_state(
        self,
        login: str,
        portable_mode: bool,
        proxy_url: str | None,
        interface_ip: str | None,
    ) -> None:
        entry = self._data.setdefault(login, {})
        entry["last_launch_portable_mode"] = portable_mode
        entry["last_launch_proxy_url"] = proxy_url
        entry["last_launch_interface_ip"] = interface_ip

    def state_changed_since_last_launch(
        self,
        login: str,
        portable_mode: bool,
        proxy_url: str | None,
        interface_ip: str | None,
    ) -> bool:
        entry = self._data.get(login) or {}
        return (
            entry.get("last_launch_portable_mode") != portable_mode
            or entry.get("last_launch_proxy_url") != proxy_url
            or entry.get("last_launch_interface_ip") != interface_ip
        )

    def is_proxy_used(self, proxy_url: str, exclude_login: str | None = None) -> bool:
        for login, entry in self._data.items():
            if login == exclude_login:
                continue
            if entry.get("proxy_url") == proxy_url:
                return True
        return False

    def remove(self, login: str) -> None:
        self._data.pop(login, None)

    def all_entries(self) -> dict[str, dict]:
        return dict(self._data)


class _DemoServer:
    handler = None
    _pid = 8000

    def launch_dofus(
        self,
        login: str,
        proxy_listener: object = None,
        proxy_url: str | None = None,
        interface_ip: str | None = None,
        on_progress: Callable[[str], None] | None = None,
    ) -> int:
        del proxy_listener
        return self._launch("Dofus 3", login, proxy_url, interface_ip, on_progress)

    def launch_retro(
        self,
        login: str,
        proxy_url: str | None = None,
        interface_ip: str | None = None,
        on_progress: Callable[[str], None] | None = None,
    ) -> int:
        return self._launch("Dofus Retro", login, proxy_url, interface_ip, on_progress)

    def _launch(
        self,
        game: str,
        login: str,
        proxy_url: str | None,
        interface_ip: str | None,
        on_progress: Callable[[str], None] | None,
    ) -> int:
        for step, text in enumerate(
            [
                f"Preparing {game} for {login} (1 / 4)",
                f"Interface: {interface_ip or 'Auto'} (2 / 4)",
                f"Proxy: {proxy_url or 'None'} (3 / 4)",
                "Demo launch complete (4 / 4)",
            ],
            start=1,
        ):
            del step
            if on_progress is not None:
                on_progress(text)
        self.__class__._pid += 1
        return self._pid


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Open AnkAlt Launcher GUI with a fake backend."
    )
    parser.add_argument(
        "--offscreen",
        action="store_true",
        help="Use QT_QPA_PLATFORM=offscreen before importing Qt.",
    )
    parser.add_argument(
        "--smoke",
        action="store_true",
        help="Open the harness, trigger a few demo actions, then exit.",
    )
    parser.add_argument(
        "--empty",
        action="store_true",
        help="Start with the empty-state account list.",
    )
    parser.add_argument(
        "--no-controls",
        action="store_true",
        help="Show only the production main window with fake data.",
    )
    return parser.parse_args(argv)


def _run_inline(
    func: Callable[[Callable[[str], None]], object],
    on_success: Callable[[object], None] | None = None,
    on_error: Callable[[object], None] | None = None,
    on_progress: Callable[[str], None] | None = None,
    parent: object | None = None,
) -> None:
    del parent
    try:
        result = func(on_progress or (lambda _msg: None))
    except Exception as exc:
        if on_error is not None:
            on_error(exc)
        return
    if on_success is not None:
        on_success(result)


def _fake_has_active_credentials(login: str) -> bool:
    return login in READY_LOGINS


def _fake_verify_proxy_ip(_proxy_url: str) -> str:
    return "198.51.100.77"


def _fake_build_proxy_listener(proxy_url: str | None) -> tuple[None, str | None]:
    return None, proxy_url


def _apply_demo_dialog_style(dialog) -> None:
    dialog.setStyleSheet(DEMO_DARK_STYLESHEET)


def _style_demo_account_card(card) -> None:
    from PyQt6.QtGui import QColor, QPalette

    card.setObjectName("demoAccountCard")
    card.setAutoFillBackground(True)
    palette = card.palette()
    palette.setColor(QPalette.ColorRole.Window, QColor(PANEL_BG))
    palette.setColor(QPalette.ColorRole.Base, QColor(PANEL_BG))
    palette.setColor(QPalette.ColorRole.AlternateBase, QColor(PANEL_ALT))
    palette.setColor(QPalette.ColorRole.Text, QColor(TEXT))
    palette.setColor(QPalette.ColorRole.WindowText, QColor(TEXT))
    palette.setColor(QPalette.ColorRole.ButtonText, QColor(TEXT))
    card.setPalette(palette)
    card.setStyleSheet(
        "CardWidget#demoAccountCard, AccountCard#demoAccountCard {"
        f"background-color: {PANEL_BG};"
        f"border: 1px solid {BORDER};"
        "border-radius: 18px;"
        "}"
        "CardWidget#demoAccountCard BodyLabel, AccountCard#demoAccountCard BodyLabel,"
        "CardWidget#demoAccountCard QLabel, AccountCard#demoAccountCard QLabel {"
        f"color: {TEXT};"
        "}"
        "CardWidget#demoAccountCard CaptionLabel, AccountCard#demoAccountCard CaptionLabel {"
        f"color: {TEXT_MUTED};"
        "}"
        "CardWidget#demoAccountCard ComboBox, AccountCard#demoAccountCard ComboBox,"
        "CardWidget#demoAccountCard PushButton, AccountCard#demoAccountCard PushButton,"
        "CardWidget#demoAccountCard PrimaryPushButton, AccountCard#demoAccountCard PrimaryPushButton {"
        f"background-color: {PANEL_ALT};"
        f"color: {TEXT};"
        f"border: 1px solid {BORDER};"
        "min-height: 28px;"
        "max-height: 28px;"
        "border-radius: 14px;"
        "padding: 2px 10px;"
        "}"
    )


def _install_fakes(stack: ExitStack) -> None:
    with (
        patch("os.system", return_value=1),
        contextlib.redirect_stdout(io.StringIO()),
    ):
        from ankama_launcher_emulator.gui import account_card
        from ankama_launcher_emulator.gui import add_account_dialog
        from ankama_launcher_emulator.gui import main_window
        from ankama_launcher_emulator.gui import portable_account_dialogs
        from ankama_launcher_emulator.gui import proxy_dialog
        from ankama_launcher_emulator.gui.add_account_dialog import AddAccountDialog
        from ankama_launcher_emulator.gui.portable_account_dialogs import (
            PortableAccountExportDialog,
            PortableAccountImportDialog,
        )
        from ankama_launcher_emulator.gui.proxy_dialog import ProxyDialog

    stack.enter_context(patch.object(main_window, "ProxyStore", _DemoProxyStore))
    stack.enter_context(patch.object(main_window, "AccountMeta", _DemoAccountMeta))
    stack.enter_context(patch.object(main_window, "DOFUS_INSTALLED", True))
    stack.enter_context(patch.object(main_window, "RETRO_INSTALLED", True))
    stack.enter_context(patch.object(main_window, "CYTRUS_INSTALLED", False))
    stack.enter_context(patch.object(main_window, "run_in_background", _run_inline))
    stack.enter_context(
        patch.object(main_window, "verify_proxy_ip", _fake_verify_proxy_ip)
    )
    stack.enter_context(
        patch.object(main_window, "build_proxy_listener", _fake_build_proxy_listener)
    )
    stack.enter_context(
        patch.object(main_window.MainWindow, "_start_refresh_timer", lambda self: None)
    )

    def fake_open_proxy_dialog(window) -> None:
        dialog = ProxyDialog(window._proxy_store, parent=window)
        _apply_demo_dialog_style(dialog)
        dialog.exec()
        for card in window._cards:
            card.update_proxies()

    def fake_open_add_account_dialog(window) -> None:
        dialog = AddAccountDialog(window._proxy_store, parent=window)
        _apply_demo_dialog_style(dialog)

        def fake_add() -> None:
            login = dialog._login_input.text().strip() or "new.demo@example.com"
            alias = dialog._alias_input.text().strip() or "Demo account"
            READY_LOGINS.add(login)
            _DemoAccountMeta().set_meta(login, alias=alias)
            account = {"apikey": {"login": login}}
            _style_demo_account_card(window._add_card(account, DEMO_INTERFACES))
            window._accounts.append(account)
            dialog._status_label.setText("Demo account added.")
            dialog.accept()

        dialog._add_btn.clicked.disconnect()
        dialog._add_btn.clicked.connect(fake_add)
        dialog._login_input.setText("new.demo@example.com")
        dialog._password_input.setText("demo-password")
        dialog._alias_input.setText("New demo alt")
        dialog.show()

    def fake_remove_account(window, login: str, card) -> None:
        if card.is_running:
            window._show_error("Stop the game before removing")
            return
        window._proxy_store.assign_proxy(login, None)
        _DemoAccountMeta().remove(login)
        window._card_layout.removeWidget(card)
        card.hide()
        card.deleteLater()
        if card in window._cards:
            window._cards.remove(card)
        window._accounts = [
            account
            for account in window._accounts
            if account["apikey"]["login"] != login
        ]
        window._sync_empty_state()
        window._show_success(f"Removed {login}")

    stack.enter_context(
        patch.object(
            main_window.MainWindow, "_open_proxy_dialog", fake_open_proxy_dialog
        )
    )
    stack.enter_context(
        patch.object(
            main_window.MainWindow,
            "_open_add_account_dialog",
            fake_open_add_account_dialog,
        )
    )
    def fake_inspect_portable_account(_path: str, _passphrase: str) -> dict:
        return {
            "version": 1,
            "exported_at": "2026-01-01T00:00:00",
            "app_version": "0.1.0",
            "login": "ready.alt@example.com",
            "account_id": 7,
            "alias": "Cra",
            "portable_mode": True,
            "fake_uuid": "demo-uuid",
            "fake_hm1": "a" * 32,
            "fake_hm2": "b" * 32,
            "fake_hostname": "DESKTOP-DEMO1",
            "proxy_url": _DemoProxyStore._proxies["paris"].url,
            "cert_validated_proxy_url": _DemoProxyStore._proxies["paris"].url,
            "keydata": {
                "key": "access-token",
                "provider": "ankama",
                "refreshToken": "refresh-token",
                "isStayLoggedIn": True,
                "accountId": 7,
                "login": "ready.alt@example.com",
                "refreshDate": 1,
            },
            "certificate": {
                "id": 42,
                "encodedCertificate": "abc",
                "login": "ready.alt@example.com",
            },
        }

    def fake_open_import_account_dialog(window) -> None:
        dialog = PortableAccountImportDialog(parent=window)
        _apply_demo_dialog_style(dialog)
        dialog._path_input.setText("/tmp/demo-portable-account.ankalt-account")
        dialog._passphrase_input.setText("demo-passphrase")
        if (
            dialog.exec() == dialog.DialogCode.Accepted
            and dialog.preview_payload()
        ):
            window._show_success(
                f"Demo import ready for {dialog.preview_payload()['login']}"
            )

    def fake_open_export_account_dialog(window, login: str | None = None) -> None:
        target_login = login or "ready.alt@example.com"
        entry = _DemoAccountMeta().get(target_login) or {}
        dialog = PortableAccountExportDialog(
            login=target_login,
            alias=cast(str | None, entry.get("alias")),
            has_proxy=bool(entry.get("proxy_url")),
            has_certificate=True,
            parent=window,
        )
        _apply_demo_dialog_style(dialog)
        if dialog.exec() == dialog.DialogCode.Accepted:
            window._show_success(f"Demo export ready for {target_login}")

    stack.enter_context(
        patch.object(
            portable_account_dialogs,
            "inspect_portable_account",
            fake_inspect_portable_account,
        )
    )
    stack.enter_context(
        patch.object(
            main_window.MainWindow,
            "_open_import_account_dialog",
            fake_open_import_account_dialog,
        )
    )
    stack.enter_context(
        patch.object(
            main_window.MainWindow,
            "_open_export_account_dialog",
            fake_open_export_account_dialog,
        )
    )
    stack.enter_context(
        patch.object(main_window.MainWindow, "_on_remove_account", fake_remove_account)
    )
    stack.enter_context(patch.object(account_card, "AccountMeta", _DemoAccountMeta))
    stack.enter_context(
        patch.object(
            account_card, "has_active_credentials", _fake_has_active_credentials
        )
    )
    stack.enter_context(patch.object(account_card, "run_in_background", _run_inline))
    stack.enter_context(
        patch.object(
            account_card.AccountCard,
            "_stop_process",
            lambda self: self._on_process_ended(),
        )
    )
    stack.enter_context(
        patch.object(add_account_dialog, "AccountMeta", _DemoAccountMeta)
    )
    stack.enter_context(patch.object(proxy_dialog, "run_in_background", _run_inline))


def _clear_cards(window) -> None:
    for card in window._cards[:]:
        window._card_layout.removeWidget(card)
        card.hide()
        card.deleteLater()
    window._cards.clear()
    window._accounts = []
    window._sync_empty_state()


def _reset_cards(window) -> None:
    _clear_cards(window)
    for account in DEMO_ACCOUNTS:
        _style_demo_account_card(window._add_card(account, DEMO_INTERFACES))
    window._accounts = list(DEMO_ACCOUNTS)
    window._sync_empty_state()


def _patch_window_dialogs(window) -> None:
    from PyQt6.QtWidgets import QDialog

    from ankama_launcher_emulator.gui.add_account_dialog import AddAccountDialog
    from ankama_launcher_emulator.gui.proxy_dialog import ProxyDialog
    from ankama_launcher_emulator.gui.shield_dialog import ShieldCodeDialog

    def open_proxy_dialog() -> None:
        dialog = ProxyDialog(window._proxy_store, parent=window)
        _apply_demo_dialog_style(dialog)
        dialog.exec()
        for card in window._cards:
            card.update_proxies()

    def open_add_account_dialog() -> None:
        dialog = AddAccountDialog(window._proxy_store, parent=window)
        _apply_demo_dialog_style(dialog)

        def fake_add() -> None:
            login = dialog._login_input.text().strip() or "new.demo@example.com"
            alias = dialog._alias_input.text().strip() or "Demo account"
            READY_LOGINS.add(login)
            _DemoAccountMeta().set_meta(login, alias=alias)
            _style_demo_account_card(
                window._add_card({"apikey": {"login": login}}, DEMO_INTERFACES)
            )
            window._accounts.append({"apikey": {"login": login}})
            dialog._status_label.setText("Demo account added.")
            dialog.accept()

        dialog._add_btn.clicked.disconnect()
        dialog._add_btn.clicked.connect(fake_add)
        dialog._login_input.setText("new.demo@example.com")
        dialog._password_input.setText("demo-password")
        dialog._alias_input.setText("New demo alt")
        dialog.show()

    def open_shield_dialog() -> None:
        dialog = ShieldCodeDialog("ready.alt@example.com", parent=window)
        _apply_demo_dialog_style(dialog)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            window._show_success(f"Shield code accepted: {dialog.get_code()}")

    def open_import_dialog() -> None:
        window._open_import_account_dialog()

    def open_export_dialog() -> None:
        window._open_export_account_dialog("ready.alt@example.com")

    window._open_proxy_dialog = open_proxy_dialog
    window._open_add_account_dialog = open_add_account_dialog
    window._open_demo_shield_dialog = open_shield_dialog
    window._open_demo_import_dialog = open_import_dialog
    window._open_demo_export_dialog = open_export_dialog


class _DemoControls:
    def __init__(self, window) -> None:
        from PyQt6.QtCore import Qt
        from PyQt6.QtWidgets import QHBoxLayout, QVBoxLayout, QWidget
        from qfluentwidgets import BodyLabel, CardWidget, CaptionLabel, PushButton

        self._window = window
        self._banner_step = 0
        self._cytrus_installed = True
        self._update_step = 0
        self.widget = QWidget()
        self.widget.setObjectName("demoControls")
        self.widget.setWindowTitle("AnkAlt GUI Demo Controls")
        self.widget.resize(380, 640)
        self.widget.setStyleSheet(DEMO_DARK_STYLESHEET)

        layout = QVBoxLayout(self.widget)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(10)

        header = BodyLabel("GUI Demo Controls")
        layout.addWidget(header)

        hint = CaptionLabel("All actions use in-memory fake data.")
        hint.setWordWrap(True)
        layout.addWidget(hint)

        self._cytrus_status = CaptionLabel("")
        self._cytrus_status.setWordWrap(True)
        layout.addWidget(self._cytrus_status)
        self._sync_cytrus_state()

        card = CardWidget()
        row_layout = QVBoxLayout(card)
        row_layout.setContentsMargins(14, 14, 14, 14)
        row_layout.setSpacing(8)
        layout.addWidget(card)

        for label, callback in [
            ("Cycle Download Banner", self._cycle_banner),
            ("Hide Download Banner", lambda: window._set_panel_status("")),
            ("Show Update Banner", self._show_update_banner),
            ("Hide Update Banner", self._hide_update_banner),
            ("Cycle Update Banner", self._cycle_update_banner),
            ("Open Add Account", window._open_add_account_dialog),
            ("Open Import Dialog", window._open_demo_import_dialog),
            ("Open Export Dialog", window._open_demo_export_dialog),
            ("Open Proxy Library", window._open_proxy_dialog),
            ("Open Shield Dialog", window._open_demo_shield_dialog),
            ("Fake Launch First Account", self._launch_first_account),
            ("Toggle Cytrus Installed", self._toggle_cytrus_installed),
            ("Simulate Game Update", self._simulate_game_update),
            ("Switch to Dofus 3", lambda: window._select_game(True)),
            ("Switch to Retro", lambda: window._select_game(False)),
            ("Show Success InfoBar", lambda: window._show_success("Demo success")),
            ("Show Error InfoBar", lambda: window._show_error("Demo error")),
            ("Toggle Empty State", self._toggle_empty_state),
        ]:
            button = PushButton(label)
            button.clicked.connect(callback)
            row_layout.addWidget(button)

        launch_row = QHBoxLayout()
        stop_button = PushButton("Stop Running Cards")
        stop_button.clicked.connect(self._stop_running_cards)
        launch_row.addWidget(stop_button)
        row_layout.addLayout(launch_row)
        layout.addStretch()

        self.widget.setWindowFlag(Qt.WindowType.Tool, True)

    def _cycle_banner(self) -> None:
        statuses = [
            "Checking cytrus packages (1 / 5)",
            "Downloading manifest (2 / 5)",
            "Downloading update archive (3 / 5)",
            "Extracting files (4 / 5)",
            "Ready to launch (5 / 5)",
        ]
        self._window._set_panel_status(statuses[self._banner_step % len(statuses)])
        self._banner_step += 1

    def _show_update_banner(self) -> None:
        banner = self._window._update_banner
        banner.set_info("0.99.0", "https://github.com/Valentin-alix/AnkamaLauncherEmulator/releases/tag/v0.99.0")
        banner.show()

    def _hide_update_banner(self) -> None:
        self._window._update_banner.hide()

    def _cycle_update_banner(self) -> None:
        versions = [
            ("0.6.0", "https://github.com/Valentin-alix/AnkamaLauncherEmulator/releases/tag/v0.6.0"),
            ("0.7.0", "https://github.com/Valentin-alix/AnkamaLauncherEmulator/releases/tag/v0.7.0"),
            ("0.99.0", "https://github.com/Valentin-alix/AnkamaLauncherEmulator/releases/tag/v0.99.0"),
        ]
        version, url = versions[self._update_step % len(versions)]
        banner = self._window._update_banner
        banner.set_info(version, url)
        banner.show()
        self._update_step += 1

    def _sync_cytrus_state(self) -> None:
        warning_card = getattr(self._window, "_warning_card", None)
        if warning_card is not None:
            warning_card.setVisible(not self._cytrus_installed)
        state = "installed" if self._cytrus_installed else "missing"
        self._cytrus_status.setText(f"Cytrus demo state: {state}")

    def _toggle_cytrus_installed(self) -> None:
        self._cytrus_installed = not self._cytrus_installed
        self._sync_cytrus_state()
        message = (
            "cytrus-v6 detected by demo harness"
            if self._cytrus_installed
            else "cytrus-v6 missing in demo harness"
        )
        self._window._set_panel_status(message)

    def _simulate_game_update(self) -> None:
        from PyQt6.QtCore import QTimer

        self._cytrus_installed = True
        self._sync_cytrus_state()
        self._update_step += 1
        statuses = [
            "cytrus-v6: checking Dofus package (1 / 6)",
            "cytrus-v6: resolving release channel (2 / 6)",
            "cytrus-v6: downloading game update (3 / 6)",
            "cytrus-v6: extracting game files (4 / 6)",
            "cytrus-v6: validating installation (5 / 6)",
            "cytrus-v6: update ready (6 / 6)",
        ]
        for index, status in enumerate(statuses):
            QTimer.singleShot(
                index * 450,
                lambda text=status: self._window._set_panel_status(text),
            )
        QTimer.singleShot(
            len(statuses) * 450 + 700,
            lambda: self._window._set_panel_status(""),
        )

    def _launch_first_account(self) -> None:
        if not self._window._cards:
            _reset_cards(self._window)
        card = self._window._cards[0]
        card.set_launch_enabled(False)
        handler = self._window._make_launch_handler(card.login, card)
        handler(None, None)

    def _toggle_empty_state(self) -> None:
        if self._window._cards:
            _clear_cards(self._window)
        else:
            _reset_cards(self._window)

    def _stop_running_cards(self) -> None:
        for card in self._window._cards:
            if card.is_running:
                card._on_process_ended()


def run_demo_gui(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    if args.offscreen:
        os.environ["QT_QPA_PLATFORM"] = "offscreen"

    with ExitStack() as stack:
        _install_fakes(stack)

        from PyQt6.QtCore import QTimer
        from qfluentwidgets import Theme, setTheme

        from ankama_launcher_emulator.gui.app import ensure_app, set_app_icon
        from ankama_launcher_emulator.gui.main_window import MainWindow
        from ankama_launcher_emulator.server.server import AnkamaLauncherServer

        app = ensure_app()
        setTheme(Theme.DARK)
        set_app_icon(app)

        accounts = [] if args.empty else list(DEMO_ACCOUNTS)
        window = MainWindow(
            cast(AnkamaLauncherServer, _DemoServer()),
            accounts,
            DEMO_INTERFACES,
        )
        for card in window._cards:
            _style_demo_account_card(card)
        _patch_window_dialogs(window)
        window.show()

        controls = None
        if not args.no_controls:
            controls = _DemoControls(window)
            controls.widget.show()

        if args.smoke:
            window._set_panel_status("Smoke test progress (1 / 2)")
            window._select_game(False)
            if controls is not None:
                controls._toggle_empty_state()
                controls._toggle_empty_state()
            QTimer.singleShot(100, app.quit)

        return app.exec()


def main() -> int:
    return run_demo_gui()


if __name__ == "__main__":
    raise SystemExit(main())
