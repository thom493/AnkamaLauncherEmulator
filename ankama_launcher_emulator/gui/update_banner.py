import webbrowser

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QHBoxLayout, QLabel, QVBoxLayout, QWidget
from qfluentwidgets import BodyLabel, CardWidget, PushButton

from ankama_launcher_emulator.gui.consts import (
    BORDER_HEXA,
    ORANGE_HEXA,
    ORANGE_HOVER_HEXA,
    PANEL_ALT_HEXA,
    PANEL_BG_HEXA,
    TEXT_DIM_HEXA,
    TEXT_HEXA,
)


class UpdateBanner(QWidget):
    """Persistent update notification banner that sits at the top of the content area."""

    def __init__(self, version: str, html_url: str, parent=None):
        super().__init__(parent)
        self._version = version
        self._html_url = html_url
        self._setup_ui()

    def _setup_ui(self) -> None:
        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 8, 12, 8)
        layout.setSpacing(10)

        card = CardWidget()
        card.setStyleSheet(
            "CardWidget {"
            f"background-color: {PANEL_BG_HEXA};"
            f"border: 1px solid {BORDER_HEXA};"
            "border-radius: 16px;"
            "}"
        )
        card_layout = QHBoxLayout(card)
        card_layout.setContentsMargins(14, 10, 14, 10)
        card_layout.setSpacing(12)

        text_layout = QVBoxLayout()
        text_layout.setSpacing(2)
        self._title_label = BodyLabel(f"AnkAlt v{self._version} is available.")
        self._title_label.setStyleSheet(f"color: {TEXT_HEXA};")
        text_layout.addWidget(self._title_label)

        hint = BodyLabel("A new release is out on GitHub.")
        hint.setStyleSheet(f"color: {TEXT_DIM_HEXA};")
        text_layout.addWidget(hint)
        card_layout.addLayout(text_layout, 1)

        open_btn = PushButton("Open Release")
        open_btn.setFixedHeight(28)
        open_btn.setStyleSheet(
            "PushButton {"
            f"background-color: {ORANGE_HEXA};"
            f"color: {TEXT_HEXA};"
            "border: none;"
            "border-radius: 14px;"
            "padding: 2px 12px;"
            "}"
            "PushButton:hover {"
            f"background-color: {ORANGE_HOVER_HEXA};"
            "}"
        )
        open_btn.clicked.connect(self._open_release)
        card_layout.addWidget(open_btn)

        skip_btn = PushButton("Skip")
        skip_btn.setFixedHeight(28)
        skip_btn.setStyleSheet(
            "PushButton {"
            f"background-color: {PANEL_ALT_HEXA};"
            f"color: {TEXT_HEXA};"
            f"border: 1px solid {BORDER_HEXA};"
            "border-radius: 14px;"
            "padding: 2px 12px;"
            "}"
            "PushButton:hover {"
            f"border-color: {ORANGE_HEXA};"
            "}"
        )
        skip_btn.clicked.connect(self._skip_version)
        card_layout.addWidget(skip_btn)

        close_btn = PushButton("✕")
        close_btn.setFixedSize(28, 28)
        close_btn.setStyleSheet(skip_btn.styleSheet())
        close_btn.clicked.connect(self.hide)
        card_layout.addWidget(close_btn)

        layout.addWidget(card)
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
