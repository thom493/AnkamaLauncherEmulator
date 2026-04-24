"""Proxy library management dialog."""

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QVBoxLayout,
    QWidget,
)
from qfluentwidgets import (
    BodyLabel,
    CaptionLabel,
    CardWidget,
    LineEdit,
    PrimaryPushButton,
    PushButton,
    ScrollArea,
)

from ankama_launcher_emulator.gui.consts import (
    APP_BG_HEXA,
    BORDER_HEXA,
    ORANGE_HEXA,
    PANEL_ALT_HEXA,
    PANEL_BG_HEXA,
    TEXT_MUTED_HEXA,
    TEXT_SOFT_HEXA,
)
from ankama_launcher_emulator.gui.utils import run_in_background
from ankama_launcher_emulator.utils.proxy_store import ProxyStore

CONTROL_HEIGHT = 28


def _compact_control_style(kind: str = "PushButton") -> str:
    return (
        f"{kind} {{"
        f"background-color: {PANEL_ALT_HEXA};"
        f"border: 1px solid {BORDER_HEXA};"
        "border-radius: 14px;"
        "padding: 2px 10px;"
        "}"
        f"{kind}:hover {{ border-color: {ORANGE_HEXA}; }}"
    )


class _ProxyRow(CardWidget):
    """Single proxy entry row."""

    def __init__(
        self,
        proxy_id: str,
        name: str,
        url: str,
        exit_ip: str | None,
        store: ProxyStore,
        parent=None,
    ):
        super().__init__(parent)
        self.proxy_id = proxy_id
        self._store = store
        self._dialog = parent

        self.setStyleSheet(
            "CardWidget {"
            f"background-color: {PANEL_BG_HEXA};"
            f"border: 1px solid {BORDER_HEXA};"
            "border-radius: 14px;"
            "}"
            f"CardWidget CaptionLabel {{ color: {TEXT_MUTED_HEXA}; }}"
        )

        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 4, 10, 4)
        layout.setSpacing(6)

        self._name_label = BodyLabel(name)
        self._name_label.setFixedWidth(120)
        layout.addWidget(self._name_label)

        self._url_label = CaptionLabel(url)
        self._url_label.setWordWrap(False)
        layout.addWidget(self._url_label, 1)

        self._ip_label = CaptionLabel(exit_ip or "—")
        self._ip_label.setFixedWidth(120)
        layout.addWidget(self._ip_label)

        self._test_btn = PushButton("Test")
        self._test_btn.setFixedWidth(60)
        self._test_btn.setFixedHeight(CONTROL_HEIGHT)
        self._test_btn.setStyleSheet(_compact_control_style())
        self._test_btn.clicked.connect(self._on_test)
        layout.addWidget(self._test_btn)

        self._edit_btn = PushButton("Edit")
        self._edit_btn.setFixedWidth(60)
        self._edit_btn.setFixedHeight(CONTROL_HEIGHT)
        self._edit_btn.setStyleSheet(_compact_control_style())
        self._edit_btn.clicked.connect(self._on_edit)
        layout.addWidget(self._edit_btn)

        self._del_btn = PushButton("Del")
        self._del_btn.setFixedWidth(50)
        self._del_btn.setFixedHeight(CONTROL_HEIGHT)
        self._del_btn.setStyleSheet(_compact_control_style())
        self._del_btn.clicked.connect(self._on_delete)
        layout.addWidget(self._del_btn)

    def _on_test(self) -> None:
        self._test_btn.setDisabled(True)
        self._test_btn.setText("...")

        pid = self.proxy_id

        def task(_on_progress: object) -> str | None:
            return self._store.test_proxy(pid)

        def on_success(ip: object) -> None:
            self._test_btn.setEnabled(True)
            self._test_btn.setText("Test")
            self._ip_label.setText(str(ip) if ip else "Failed")

        def on_error(_err: object) -> None:
            self._test_btn.setEnabled(True)
            self._test_btn.setText("Test")
            self._ip_label.setText("Error")

        run_in_background(task, on_success=on_success, on_error=on_error, parent=self)

    def _on_edit(self) -> None:
        dialog = _ProxyEditDialog(
            self._name_label.text(),
            self._url_label.text(),
            parent=self,
        )
        if dialog.exec() == QDialog.DialogCode.Accepted:
            name, url = dialog.get_values()
            self._store.update_proxy(self.proxy_id, name=name, url=url)
            self._name_label.setText(name)
            self._url_label.setText(url)

    def _on_delete(self) -> None:
        self._store.remove_proxy(self.proxy_id)
        if self._dialog and hasattr(self._dialog, "_refresh_list"):
            self._dialog._refresh_list()


class _ProxyEditDialog(QDialog):
    """Mini dialog for editing proxy name + URL."""

    def __init__(self, name: str, url: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Edit Proxy")
        self.setMinimumWidth(400)
        self.setStyleSheet(
            "QDialog {"
            f"background-color: {APP_BG_HEXA};"
            "}"
            f"QDialog BodyLabel {{ color: {TEXT_SOFT_HEXA}; }}"
            f"QDialog LineEdit {{ background-color: {PANEL_ALT_HEXA}; border: 1px solid {BORDER_HEXA}; border-radius: 14px; padding: 2px 10px; }}"
        )

        layout = QVBoxLayout(self)
        layout.setSpacing(8)
        layout.setContentsMargins(14, 14, 14, 14)

        layout.addWidget(BodyLabel("Name"))
        self._name_input = LineEdit()
        self._name_input.setText(name)
        self._name_input.setFixedHeight(CONTROL_HEIGHT)
        layout.addWidget(self._name_input)

        layout.addWidget(BodyLabel("URL"))
        self._url_input = LineEdit()
        self._url_input.setText(url)
        self._url_input.setPlaceholderText("socks5://user:pass@host:port")
        self._url_input.setFixedHeight(CONTROL_HEIGHT)
        layout.addWidget(self._url_input)

        btn_row = QHBoxLayout()
        save_btn = PrimaryPushButton("Save")
        save_btn.setFixedHeight(CONTROL_HEIGHT)
        save_btn.setStyleSheet(_compact_control_style("PrimaryPushButton"))
        save_btn.clicked.connect(self.accept)
        cancel_btn = PushButton("Cancel")
        cancel_btn.setFixedHeight(CONTROL_HEIGHT)
        cancel_btn.setStyleSheet(_compact_control_style())
        cancel_btn.clicked.connect(self.reject)
        btn_row.addWidget(save_btn)
        btn_row.addWidget(cancel_btn)
        layout.addLayout(btn_row)

    def get_values(self) -> tuple[str, str]:
        return self._name_input.text().strip(), self._url_input.text().strip()


class ProxyDialog(QDialog):
    """Proxy library management dialog."""

    def __init__(self, store: ProxyStore, parent=None):
        super().__init__(parent)
        self._store = store
        self.setWindowTitle("Proxy Library")
        self.setMinimumSize(700, 400)
        self.setStyleSheet(
            "QDialog {"
            f"background-color: {APP_BG_HEXA};"
            "}"
            f"QDialog BodyLabel {{ color: {TEXT_SOFT_HEXA}; }}"
            f"QDialog CaptionLabel {{ color: {TEXT_MUTED_HEXA}; }}"
        )
        self._setup_ui()
        self._refresh_list()

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setSpacing(12)
        layout.setContentsMargins(16, 16, 16, 16)

        # Header
        header = QHBoxLayout()
        header.addWidget(BodyLabel("Manage your proxies"))
        header.addStretch()
        add_btn = PrimaryPushButton("+ Add Proxy")
        add_btn.setFixedHeight(CONTROL_HEIGHT)
        add_btn.setStyleSheet(_compact_control_style("PrimaryPushButton"))
        add_btn.clicked.connect(self._on_add)
        header.addWidget(add_btn)
        layout.addLayout(header)

        # Column headers
        col_header = QHBoxLayout()
        col_header.setContentsMargins(12, 0, 12, 0)
        name_h = CaptionLabel("Name")
        name_h.setFixedWidth(120)
        col_header.addWidget(name_h)
        col_header.addWidget(CaptionLabel("URL"), 1)
        ip_h = CaptionLabel("Exit IP")
        ip_h.setFixedWidth(120)
        col_header.addWidget(ip_h)
        col_header.addSpacing(180)  # buttons space
        layout.addLayout(col_header)

        # Scroll area for proxy rows
        self._scroll = ScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll_content = QWidget()
        self._scroll_layout = QVBoxLayout(self._scroll_content)
        self._scroll_layout.setSpacing(6)
        self._scroll_layout.setContentsMargins(0, 0, 0, 0)
        self._scroll_layout.addStretch()
        self._scroll.setWidget(self._scroll_content)
        layout.addWidget(self._scroll, 1)

        # Close
        close_btn = PushButton("Close")
        close_btn.setFixedHeight(CONTROL_HEIGHT)
        close_btn.setStyleSheet(_compact_control_style())
        close_btn.clicked.connect(self.accept)
        layout.addWidget(close_btn, alignment=Qt.AlignmentFlag.AlignRight)

    def _refresh_list(self) -> None:
        # Clear existing rows
        while self._scroll_layout.count() > 1:  # keep stretch
            item = self._scroll_layout.takeAt(0)
            widget = item.widget() if item else None
            if widget:
                widget.deleteLater()

        proxies = self._store.list_proxies()
        for pid, entry in proxies.items():
            row = _ProxyRow(
                pid, entry.name, entry.url, entry.exit_ip, self._store, parent=self
            )
            self._scroll_layout.insertWidget(self._scroll_layout.count() - 1, row)

    def _on_add(self) -> None:
        dialog = _ProxyEditDialog("", "", parent=self)
        dialog.setWindowTitle("Add Proxy")
        if dialog.exec() == QDialog.DialogCode.Accepted:
            name, url = dialog.get_values()
            if url:
                self._store.add_proxy(name or url[:40], url)
                self._refresh_list()
