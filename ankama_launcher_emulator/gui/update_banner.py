import webbrowser

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QHBoxLayout, QWidget
from qfluentwidgets import BodyLabel, PushButton

from ankama_launcher_emulator.gui.consts import ORANGE_HEXA, TEXT_HEXA


class UpdateBanner(QWidget):
    """Compact single-line update banner with an orange accent background."""

    def __init__(self, version: str, html_url: str, parent=None):
        super().__init__(parent)
        self._version = version
        self._html_url = html_url
        self._setup_ui()

    def _setup_ui(self) -> None:
        layout = QHBoxLayout(self)
        layout.setContentsMargins(14, 8, 14, 8)
        layout.setSpacing(10)

        self.setStyleSheet(
            "UpdateBanner {"
            f"background-color: {ORANGE_HEXA};"
            "border-radius: 16px;"
            "}"
        )

        self._title_label = BodyLabel(f"AnkAlt v{self._version} is available.")
        self._title_label.setStyleSheet(
            f"color: {TEXT_HEXA}; font-weight: bold;"
        )
        layout.addWidget(self._title_label)
        layout.addStretch()

        open_btn = PushButton("Open Release")
        open_btn.setFixedHeight(28)
        open_btn.setStyleSheet(
            "PushButton {"
            "background-color: #ffffff;"
            "color: #000000;"
            "border: none;"
            "border-radius: 14px;"
            "padding: 2px 14px;"
            "font-weight: bold;"
            "}"
            "PushButton:hover {"
            "background-color: #f0f0f0;"
            "}"
        )
        open_btn.clicked.connect(self._open_release)
        layout.addWidget(open_btn)

        skip_btn = PushButton("Skip")
        skip_btn.setFixedHeight(28)
        skip_btn.setStyleSheet(
            "PushButton {"
            "background-color: transparent;"
            f"color: {TEXT_HEXA};"
            "border: 1px solid rgba(255,255,255,0.45);"
            "border-radius: 14px;"
            "padding: 2px 14px;"
            "}"
            "PushButton:hover {"
            "background-color: rgba(255,255,255,0.15);"
            "}"
        )
        skip_btn.clicked.connect(self._skip_version)
        layout.addWidget(skip_btn)

        close_btn = PushButton("✕")
        close_btn.setFixedSize(32, 32)
        close_btn.setStyleSheet(
            "PushButton {"
            "background-color: transparent;"
            f"color: {TEXT_HEXA};"
            "border: none;"
            "border-radius: 16px;"
            "font-size: 16px;"
            "padding: 0px;"
            "}"
            "PushButton:hover {"
            "background-color: rgba(255,255,255,0.15);"
            "}"
        )
        close_btn.clicked.connect(self.hide)
        layout.addWidget(close_btn)

        self.setVisible(False)

    def set_info(self, version: str, html_url: str) -> None:
        self._version = version
        self._html_url = html_url
        self._title_label.setText(f"AnkAlt v{version} is available.")

    def show(self) -> None:
        self.setVisible(True)

    def _open_release(self) -> None:
        webbrowser.open(self._html_url)

    def _skip_version(self) -> None:
        from ankama_launcher_emulator.utils.app_config import set_skipped_version

        set_skipped_version(self._version)
        self.hide()
