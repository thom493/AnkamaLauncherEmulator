import os

import psutil
from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QColor, QPalette
from PyQt6.QtWidgets import QGridLayout, QLabel, QVBoxLayout
from qfluentwidgets import (
    BodyLabel,
    CaptionLabel,
    CardWidget,
    ComboBox,
    PrimaryPushButton,
    PushButton,
    SwitchButton,
)

from ankama_launcher_emulator.decrypter.crypto_helper import CryptoHelper
from ankama_launcher_emulator.gui.consts import (
    BORDER_HEXA,
    GREEN_HEXA,
    ORANGE_HEXA,
    BLUE_HEXA,
    PANEL_ALT_HEXA,
    PANEL_BG_HEXA,
    TEXT_HEXA,
    TEXT_MUTED_HEXA,
)
from ankama_launcher_emulator.gui.utils import run_in_background
from ankama_launcher_emulator.utils.proxy_store import ProxyStore
from ankama_launcher_emulator.haapi.account_meta import AccountMeta

CONTROL_HEIGHT = 28


def has_active_credentials(login: str) -> bool:
    """True if the active (portable or official) folders hold both key and cert.

    Key files written by official Zaap don't follow our `.key{sha256(login)[:32]}`
    naming, so probe via getStoredApiKey (iterate + decrypt) to match the same
    lookup used at launch.
    """
    try:
        uuid_active, cert_folder, key_folder, _, _ = CryptoHelper.get_crypto_context(
            login
        )
    except (FileNotFoundError, OSError):
        return False
    cert_path = os.path.join(
        cert_folder, ".certif" + CryptoHelper.createHashFromStringSha(login)
    )
    if not os.path.exists(cert_path):
        return False
    try:
        CryptoHelper.getStoredApiKey(login, key_folder, uuid_active)
    except (StopIteration, FileNotFoundError, OSError):
        return False
    return True


class AccountCard(CardWidget):
    launch_requested = pyqtSignal(
        object, object
    )  # (interface_ip: str | None, proxy_id: str | None)
    remove_requested = pyqtSignal()
    error_occurred = pyqtSignal(str)
    reconnect_requested = pyqtSignal(str)  # login

    def __init__(
        self,
        login: str,
        all_interface: dict[str, tuple[str, str]],
        proxy_store: ProxyStore,
        parent=None,
        is_official: bool = False,
    ):
        super().__init__(parent)
        self.login = login
        self._is_official = is_official
        self._proxy_store = proxy_store
        self._current_pid: int | None = None
        self._last_proxy_url: str | None = self._proxy_store.get_proxy_url(login)
        self._setup_ui(all_interface)

        self._monitor_timer = QTimer(self)
        self._monitor_timer.setInterval(1500)
        self._monitor_timer.timeout.connect(self._check_process)

    def _setup_ui(self, all_interface: dict[str, tuple[str, str]]) -> None:
        layout = QGridLayout(self)
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setHorizontalSpacing(12)
        layout.setVerticalSpacing(10)

        self.setAutoFillBackground(True)
        palette = self.palette()
        palette.setColor(QPalette.ColorRole.Window, QColor(PANEL_BG_HEXA))
        palette.setColor(QPalette.ColorRole.Base, QColor(PANEL_BG_HEXA))
        palette.setColor(QPalette.ColorRole.WindowText, QColor(TEXT_HEXA))
        palette.setColor(QPalette.ColorRole.ButtonText, QColor(TEXT_HEXA))
        palette.setColor(QPalette.ColorRole.Text, QColor(TEXT_HEXA))
        self.setPalette(palette)

        self.setStyleSheet(
            "AccountCard {"
            f"background-color: {PANEL_BG_HEXA};"
            f"border: 1px solid {BORDER_HEXA};"
            "border-radius: 18px;"
            "}"
            f"AccountCard CaptionLabel {{ color: {TEXT_MUTED_HEXA}; }}"
            f"AccountCard ComboBox {{ background-color: {PANEL_ALT_HEXA}; border-radius: 14px; padding: 2px 10px; }}"
            "AccountCard PushButton, AccountCard PrimaryPushButton { border-radius: 14px; padding: 2px 10px; }"
        )

        self._login_label = BodyLabel(self.login)
        self._meta_label = CaptionLabel("Stored account")
        self._meta_label.setObjectName("accountMetaLabel")

        identity_layout = QVBoxLayout()
        identity_layout.setSpacing(2)
        identity_layout.addWidget(self._login_label)
        identity_layout.addWidget(self._meta_label)
        layout.addLayout(identity_layout, 0, 0)

        self._portable_switch = SwitchButton(parent=self)
        self._portable_switch.setOnText("Portable")
        self._portable_switch.setOffText("Official")

        meta = AccountMeta()
        entry = meta.get(self.login) or {}
        self._portable_switch.setChecked(entry.get("portable_mode", False))
        self._portable_switch.checkedChanged.connect(self._on_portable_toggled)
        layout.addWidget(self._portable_switch, 0, 1)

        self._status_dot = QLabel()
        self._status_dot.setFixedSize(10, 10)
        self._status_dot.setStyleSheet(
            f"background-color: {GREEN_HEXA}; border-radius: 5px;"
        )
        self._status_dot.setVisible(False)
        layout.addWidget(self._status_dot, 0, 5, alignment=Qt.AlignmentFlag.AlignCenter)

        self._ip_combo = ComboBox()
        self._ip_combo.addItem("Auto", userData=None)
        self._ip_combo.setMinimumWidth(220)
        self._ip_combo.setFixedHeight(CONTROL_HEIGHT)
        self._ip_combo.setStyleSheet(
            "ComboBox {"
            f"background-color: {PANEL_ALT_HEXA};"
            f"border: 1px solid {BORDER_HEXA};"
            "border-radius: 14px;"
            "padding: 2px 10px;"
            f"color: {TEXT_HEXA};"
            "}"
        )

        for ip_value, (display_name, public_ip) in all_interface.items():
            self._ip_combo.addItem(
                f"{display_name}\t{public_ip}",
                userData=ip_value,
            )
        layout.addWidget(self._ip_combo, 0, 2)

        self._proxy_combo = ComboBox()
        self._proxy_combo.setMinimumWidth(220)
        self._proxy_combo.setFixedHeight(CONTROL_HEIGHT)
        self._proxy_combo.setStyleSheet(self._ip_combo.styleSheet())
        self._refresh_proxy_combo()
        self._proxy_combo.currentIndexChanged.connect(self._on_proxy_changed)
        layout.addWidget(self._proxy_combo, 0, 3)

        self._test_proxy_btn = PushButton("Test")
        self._test_proxy_btn.setFixedWidth(68)
        self._test_proxy_btn.setFixedHeight(CONTROL_HEIGHT)
        self._test_proxy_btn.setStyleSheet(
            "PushButton {"
            f"background-color: {PANEL_ALT_HEXA};"
            f"border: 1px solid {BORDER_HEXA};"
            "border-radius: 14px;"
            "padding: 2px 10px;"
            f"color: {TEXT_HEXA};"
            "}"
        )
        self._test_proxy_btn.clicked.connect(self._on_test_proxy)
        layout.addWidget(self._test_proxy_btn, 0, 4)

        self._launch_btn = PrimaryPushButton("Launch")
        self._launch_btn.setFixedWidth(110)
        self._launch_btn.setFixedHeight(CONTROL_HEIGHT)
        self._launch_btn.clicked.connect(self._on_btn_clicked)
        layout.addWidget(self._launch_btn, 0, 5)
        self._refresh_launch_button()

        self._remove_btn = PushButton("X")
        self._remove_btn.setFixedSize(28, 28)
        self._remove_btn.setStyleSheet(
            "PushButton {"
            f"background-color: {PANEL_ALT_HEXA};"
            f"border: 1px solid {BORDER_HEXA};"
            "border-radius: 14px;"
            "padding: 0;"
            f"color: {TEXT_HEXA};"
            "}"
        )
        self._remove_btn.clicked.connect(self.remove_requested.emit)
        self._remove_btn.setVisible(not self._is_official)
        layout.addWidget(self._remove_btn, 0, 6)
        layout.setColumnStretch(0, 2)
        layout.setColumnStretch(1, 1)
        layout.setColumnStretch(2, 1)
        layout.setColumnStretch(3, 1)

    def _on_portable_toggled(self, checked: bool) -> None:
        AccountMeta().set_portable_mode(self.login, checked)
        self._refresh_launch_button()

    def _refresh_launch_button(self) -> None:
        if self._current_pid is not None:
            return
        if has_active_credentials(self.login):
            self._launch_btn.setText("Launch")
            self._launch_btn.setStyleSheet(
                "PrimaryPushButton {"
                f"background-color: {ORANGE_HEXA};"
                "border-radius: 14px;"
                "padding: 2px 10px;"
                f"color: {TEXT_HEXA};"
                "}"
            )
        else:
            self._launch_btn.setText("Reconnect")
            self._launch_btn.setStyleSheet(
                "PrimaryPushButton {"
                f"background-color: {BLUE_HEXA};"
                "border-radius: 14px;"
                "padding: 2px 10px;"
                f"color: {TEXT_HEXA};"
                "}"
            )

    def _refresh_proxy_combo(self) -> None:
        current_pid = self._proxy_combo.currentData()
        self._proxy_combo.blockSignals(True)
        self._proxy_combo.clear()
        self._proxy_combo.addItem("No proxy", userData=None)

        proxies = self._proxy_store.list_proxies()
        meta = AccountMeta()
        for pid, entry in proxies.items():
            label = entry.name
            if meta.is_proxy_used(entry.url, exclude_login=self.login):
                label += " [In Use]"
            elif entry.exit_ip:
                label += f" ({entry.exit_ip})"
            self._proxy_combo.addItem(label, userData=pid)

        # Restore selection
        assigned = self._proxy_store.get_assignment(self.login)
        if assigned:
            idx = self._proxy_combo.findData(assigned)
            if idx >= 0:
                self._proxy_combo.setCurrentIndex(idx)
        elif current_pid:
            idx = self._proxy_combo.findData(current_pid)
            if idx >= 0:
                self._proxy_combo.setCurrentIndex(idx)

        self._proxy_combo.blockSignals(False)

    def _on_proxy_changed(self) -> None:
        proxy_id = self._proxy_combo.currentData()
        self._proxy_store.assign_proxy(self.login, proxy_id)

        meta = AccountMeta()
        if proxy_id:
            proxy_url = self._proxy_store.get_proxy_url(self.login)
            if proxy_url and meta.is_proxy_used(proxy_url, exclude_login=self.login):
                self.error_occurred.emit(
                    "Warning: This proxy is already in use by another account."
                )
            meta.set_proxy(self.login, proxy_url)
        else:
            proxy_url = None
            meta.set_proxy(self.login, None)

        self._last_proxy_url = proxy_url

    def _on_test_proxy(self) -> None:
        proxy_id = self._proxy_combo.currentData()
        if not proxy_id:
            self.error_occurred.emit("Select a proxy first")
            return
        self._test_proxy_btn.setDisabled(True)
        self._test_proxy_btn.setText("...")

        def task(_on_progress: object) -> str | None:
            return self._proxy_store.test_proxy(proxy_id)

        def on_success(ip: object) -> None:
            self._test_proxy_btn.setEnabled(True)
            self._test_proxy_btn.setText("Test")
            if ip:
                self._refresh_proxy_combo()
            else:
                self.error_occurred.emit("Proxy test failed")

        def on_error(err: object) -> None:
            self._test_proxy_btn.setEnabled(True)
            self._test_proxy_btn.setText("Test")
            self.error_occurred.emit(f"Proxy test failed: {err}")

        run_in_background(task, on_success=on_success, on_error=on_error, parent=self)

    def _on_btn_clicked(self) -> None:
        if self._current_pid is not None:
            self._stop_process()
        elif has_active_credentials(self.login):
            self._on_launch_clicked()
        else:
            self._launch_btn.setDisabled(True)
            self.reconnect_requested.emit(self.login)

    def _on_launch_clicked(self) -> None:
        interface_ip = self._ip_combo.currentData() or None
        proxy_id = self._proxy_combo.currentData() or None

        self._launch_btn.setDisabled(True)
        self.launch_requested.emit(interface_ip, proxy_id)

    def _stop_process(self) -> None:
        if self._current_pid is None:
            return
        try:
            proc = psutil.Process(self._current_pid)
            children = proc.children(recursive=True)
            proc.terminate()
            for child in children:
                try:
                    child.terminate()
                except psutil.NoSuchProcess:
                    pass
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass

    def stop_process(self) -> None:
        self._stop_process()
        self._on_process_ended()

    def set_running(self, pid: int) -> None:
        self._current_pid = pid
        self._launch_btn.setText("Stop")
        self._launch_btn.setStyleSheet(
            "PrimaryPushButton {"
            f"background-color: {ORANGE_HEXA};"
            "border-radius: 14px;"
            "padding: 2px 10px;"
            f"color: {TEXT_HEXA};"
            "}"
        )
        self._launch_btn.setEnabled(True)
        self._status_dot.setVisible(True)
        self._meta_label.setText("Running")
        self._monitor_timer.start()

    def _check_process(self) -> None:
        if self._current_pid is None:
            self._monitor_timer.stop()
            return
        try:
            proc = psutil.Process(self._current_pid)
            if not proc.is_running() or proc.status() == psutil.STATUS_ZOMBIE:
                self._on_process_ended()
        except psutil.NoSuchProcess:
            self._on_process_ended()

    def _on_process_ended(self) -> None:
        self._current_pid = None
        self._monitor_timer.stop()
        self._launch_btn.setEnabled(True)
        self._status_dot.setVisible(False)
        self._meta_label.setText("Stored account")
        self._refresh_launch_button()

    def set_launch_enabled(self, enabled: bool) -> None:
        self._launch_btn.setEnabled(enabled)

    def refresh_launch_button(self) -> None:
        self._launch_btn.setEnabled(True)
        self._refresh_launch_button()

    @property
    def is_running(self) -> bool:
        return self._current_pid is not None

    def update_proxies(self) -> None:
        """Refresh proxy combo when proxy list changes."""
        self._refresh_proxy_combo()

    def update_interfaces(self, all_interface: dict[str, tuple[str, str]]) -> None:
        current_data = self._ip_combo.currentData()
        self._ip_combo.clear()
        self._ip_combo.addItem("Auto", userData=None)
        for ip_value, (display_name, public_ip) in all_interface.items():
            self._ip_combo.addItem(
                f"{display_name}\t{public_ip}",
                userData=ip_value,
            )
        if current_data is not None:
            idx = self._ip_combo.findData(current_data)
            if idx >= 0:
                self._ip_combo.setCurrentIndex(idx)
