import psutil
from PyQt6.QtCore import QTimer, pyqtSignal
from PyQt6.QtWidgets import QHBoxLayout, QLabel
from qfluentwidgets import (
    BodyLabel,
    CardWidget,
    ComboBox,
    PrimaryPushButton,
    PushButton,
)

from ankama_launcher_emulator.gui.consts import GREEN_HEXA
from ankama_launcher_emulator.gui.utils import run_in_background
from ankama_launcher_emulator.utils.proxy import verify_proxy_ip
from ankama_launcher_emulator.utils.proxy_store import ProxyEntry, ProxyStore


class AccountCard(CardWidget):
    launch_requested = pyqtSignal(
        object, object
    )  # (interface_ip: str | None, proxy_id: str | None)
    error_occurred = pyqtSignal(str)

    def __init__(
        self,
        login: str,
        all_interface: dict[str, tuple[str, str]],
        proxy_store: ProxyStore,
        parent=None,
    ):
        super().__init__(parent)
        self.login = login
        self._proxy_store = proxy_store
        self._current_pid: int | None = None
        self._setup_ui(all_interface)

        self._monitor_timer = QTimer(self)
        self._monitor_timer.setInterval(1500)
        self._monitor_timer.timeout.connect(self._check_process)

    def _setup_ui(self, all_interface: dict[str, tuple[str, str]]) -> None:
        layout = QHBoxLayout(self)
        layout.setContentsMargins(16, 12, 16, 12)
        layout.setSpacing(12)

        self._status_dot = QLabel()
        self._status_dot.setFixedSize(10, 10)
        self._status_dot.setStyleSheet(
            f"background-color: {GREEN_HEXA}; border-radius: 5px;"
        )
        self._status_dot.setVisible(False)
        layout.addWidget(self._status_dot)

        layout.addWidget(BodyLabel(self.login), 1)

        self._ip_combo = ComboBox()
        self._ip_combo.addItem("Auto", userData=None)
        self._ip_combo.setFixedWidth(300)

        for ip_value, (display_name, public_ip) in all_interface.items():
            self._ip_combo.addItem(
                f"{display_name}\t{public_ip}",
                userData=ip_value,
            )
        layout.addWidget(self._ip_combo)

        self._proxy_combo = ComboBox()
        self._proxy_combo.setFixedWidth(300)
        self._refresh_proxy_combo()
        self._proxy_combo.currentIndexChanged.connect(self._on_proxy_changed)
        layout.addWidget(self._proxy_combo)

        self._test_proxy_btn = PushButton("Test")
        self._test_proxy_btn.setFixedWidth(50)
        self._test_proxy_btn.clicked.connect(self._on_test_proxy)
        layout.addWidget(self._test_proxy_btn)

        self._launch_btn = PrimaryPushButton("Launch")
        self._launch_btn.setFixedWidth(100)
        self._launch_btn.clicked.connect(self._on_btn_clicked)
        layout.addWidget(self._launch_btn)

    def _refresh_proxy_combo(self) -> None:
        current_pid = self._proxy_combo.currentData()
        self._proxy_combo.blockSignals(True)
        self._proxy_combo.clear()
        self._proxy_combo.addItem("No proxy", userData=None)

        proxies = self._proxy_store.list_proxies()
        for pid, entry in proxies.items():
            label = entry.name
            if entry.exit_ip:
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
        else:
            self._on_launch_clicked()

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

    def set_running(self, pid: int) -> None:
        self._current_pid = pid
        self._launch_btn.setText("Stop")
        self._launch_btn.setEnabled(True)
        self._status_dot.setVisible(True)
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
        self._launch_btn.setText("Launch")
        self._launch_btn.setEnabled(True)
        self._status_dot.setVisible(False)

    def set_launch_enabled(self, enabled: bool) -> None:
        self._launch_btn.setEnabled(enabled)

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
