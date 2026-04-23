import re

from PyQt6.QtCore import QSize, Qt
from PyQt6.QtGui import QMovie
from PyQt6.QtWidgets import QHBoxLayout, QLabel, QVBoxLayout, QWidget, QFrame
from qfluentwidgets import CaptionLabel, ProgressBar

from ankama_launcher_emulator.consts import RESOURCES
from ankama_launcher_emulator.gui.consts import (
    BORDER_HEXA,
    ORANGE_HEXA,
    PANEL_ALT_HEXA,
    TEXT_MUTED_HEXA,
)

_STEP_RE = re.compile(r"\(?\s*(\d+)\s*/\s*(\d+)\s*\)?")


def _strip_step_text(text: str, match: re.Match[str]) -> str:
    stripped = f"{text[:match.start()]}{text[match.end():]}".strip()
    stripped = re.sub(r"\s{2,}", " ", stripped)
    return re.sub(r"\s+([,.;:])", r"\1", stripped)


class DownloadBanner(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("statusStrip")
        
        # Main horizontal layout
        main_layout = QHBoxLayout(self)
        main_layout.setContentsMargins(12, 8, 12, 8)
        main_layout.setSpacing(6)

        # 1. QMovie Label
        self._loading_label = QLabel()
        self._loading_label.setFixedSize(40, 40)
        self._loading_movie = QMovie(str(RESOURCES / "load.gif"))
        self._loading_movie.setScaledSize(QSize(40, 40))
        self._loading_label.setMovie(self._loading_movie)
        main_layout.addWidget(self._loading_label)

        # 2. Vertical layout for progress bar + label
        right_layout = QVBoxLayout()
        right_layout.setSpacing(0)
        right_layout.setAlignment(Qt.AlignmentFlag.AlignBottom)

        self._progress_bar = ProgressBar()
        self._progress_bar.setFixedHeight(10)
        # Apply style for stripe effect (diagonal moving right)
        self._progress_bar.setStyleSheet(f"""
            ProgressBar, QProgressBar {{
                background-color: rgba(255, 255, 255, 0.08);
                border: none;
                border_radius: 5px;
            }}
            ProgressBar::chunk, QProgressBar::chunk {{
                background-color: qlineargradient(spread:repeat, x1:0, y1:0, x2:0.04, y2:0.04, 
                                                stop:0 {ORANGE_HEXA}, stop:0.499 {ORANGE_HEXA}, 
                                                stop:0.5 #e67e22, stop:1 #e67e22);
                border-radius: 5px;
            }}
        """)
        right_layout.addWidget(self._progress_bar)

        self._progress_label = CaptionLabel("")
        self._progress_label.setObjectName("statusStripText")
        self._progress_label.setStyleSheet(f"color: {TEXT_MUTED_HEXA}; font-weight: bold;")
        right_layout.addWidget(self._progress_label)
        
        main_layout.addLayout(right_layout)

        self.setStyleSheet(
            "DownloadBanner {"
            f"background-color: {PANEL_ALT_HEXA};"
            f"border: 1px solid {BORDER_HEXA};"
            "border-radius: 16px;"
            "}"
        )
        self.setVisible(False)

    def set_status(self, text: str) -> None:
        if not text:
            self._loading_movie.stop()
            self.setVisible(False)
            self._progress_bar.setRange(0, 100)
            self._progress_bar.setValue(0)
            self._progress_label.setText("")
            return
        self.setVisible(True)
        self._loading_movie.start()
        match = _STEP_RE.search(text)
        if match:
            self._progress_label.setText(_strip_step_text(text, match))
            current, total = int(match.group(1)), int(match.group(2))
            if total > 0:
                self._progress_bar.setRange(0, total)
                self._progress_bar.setValue(current)
                return
        self._progress_label.setText(text)
        self._progress_bar.setRange(0, 0)
