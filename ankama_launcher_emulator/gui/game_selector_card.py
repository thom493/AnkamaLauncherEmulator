from pathlib import Path

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QFont, QMouseEvent, QPixmap
from PyQt6.QtWidgets import QFrame, QGraphicsOpacityEffect, QLabel, QVBoxLayout

from ankama_launcher_emulator.gui.consts import (
    BORDER_HEXA,
    NAV_ACTIVE_HEXA,
    NAV_INACTIVE_HEXA,
    ORANGE_HEXA,
    PANEL_ALT_HEXA,
    TEXT_DIM_HEXA,
    TEXT_MUTED_HEXA,
    TEXT_SOFT_HEXA,
)


class GameSelectorCard(QFrame):
    clicked = pyqtSignal()

    def __init__(
        self, title: str, logo_path: Path, is_active: bool, available: bool = True, parent=None
    ):
        super().__init__(parent)
        self._available = available
        self.setProperty("navRole", "game")
        self.setCursor(
            Qt.CursorShape.PointingHandCursor
            if available
            else Qt.CursorShape.ForbiddenCursor
        )
        self.setFixedSize(88, 108)
        self._setup_ui(title, logo_path)
        self.set_active(is_active)

    def _setup_ui(self, title: str, logo_path: Path) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 14, 12, 14)
        layout.setSpacing(8)

        logo = QLabel()
        pixmap = QPixmap(str(logo_path)).scaled(
            42,
            42,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        logo.setPixmap(pixmap)
        logo.setFixedSize(42, 42)
        layout.addWidget(logo, alignment=Qt.AlignmentFlag.AlignCenter)

        self._title_label = QLabel(title)
        font = self._title_label.font()
        font.setPointSize(10)
        font.setWeight(QFont.Weight.DemiBold)
        self._title_label.setFont(font)
        self._title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._title_label.setWordWrap(True)
        layout.addWidget(self._title_label)

    def set_active(self, active: bool) -> None:
        if not self._available:
            border = BORDER_HEXA
            bg = PANEL_ALT_HEXA
            text = TEXT_MUTED_HEXA
        else:
            border = ORANGE_HEXA if active else BORDER_HEXA
            bg = NAV_ACTIVE_HEXA if active else NAV_INACTIVE_HEXA
            text = TEXT_SOFT_HEXA if active else TEXT_DIM_HEXA
        self.setStyleSheet(
            "GameSelectorCard {"
            f"background-color: {bg};"
            f"border: 1px solid {border};"
            "border-radius: 18px;"
            "}"
            f"GameSelectorCard QLabel {{ color: {text}; }}"
        )
        self.setGraphicsEffect(None)
        if not self._available:
            effect = QGraphicsOpacityEffect(self)
            effect.setOpacity(0.42)
            self.setGraphicsEffect(effect)

    def mousePressEvent(self, a0: QMouseEvent | None) -> None:
        if (
            self._available
            and a0 is not None
            and a0.button() == Qt.MouseButton.LeftButton
        ):
            self.clicked.emit()
        super().mousePressEvent(a0)
