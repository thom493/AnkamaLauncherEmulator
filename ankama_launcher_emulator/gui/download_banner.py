import re

from PyQt6.QtCore import QSize, Qt
from PyQt6.QtGui import QMovie
from PyQt6.QtWidgets import QHBoxLayout, QLabel, QVBoxLayout, QWidget
from qfluentwidgets import CaptionLabel, ProgressBar

from ankama_launcher_emulator.consts import RESOURCES
from ankama_launcher_emulator.gui.consts import BORDER_HEXA, PANEL_ALT_HEXA, TEXT_MUTED_HEXA

_STEP_RE = re.compile(r"(\d+)\s*/\s*(\d+)")


class DownloadBanner(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("statusStrip")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(5)

        progress_row = QHBoxLayout()
        progress_row.setSpacing(8)

        self._loading_label = QLabel()
        self._loading_label.setFixedSize(18, 18)
        self._loading_movie = QMovie(str(RESOURCES / "load.gif"))
        self._loading_movie.setScaledSize(QSize(18, 18))
        self._loading_label.setMovie(self._loading_movie)
        progress_row.addWidget(self._loading_label)

        self._progress_bar = ProgressBar()
        self._progress_bar.setRange(0, 100)
        self._progress_bar.setValue(0)
        self._progress_bar.setFixedHeight(6)
        progress_row.addWidget(self._progress_bar, 1)
        layout.addLayout(progress_row)

        self._progress_label = CaptionLabel("")
        self._progress_label.setObjectName("statusStripText")
        self._progress_label.setAlignment(Qt.AlignmentFlag.AlignLeft)
        self._progress_label.setWordWrap(True)
        layout.addWidget(self._progress_label)

        self.setStyleSheet(
            "DownloadBanner {"
            f"background-color: {PANEL_ALT_HEXA};"
            f"border: 1px solid {BORDER_HEXA};"
            "border-radius: 16px;"
            "}"
            f"DownloadBanner #statusStripText {{ color: {TEXT_MUTED_HEXA}; }}"
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
        self._progress_label.setText(text)
        match = _STEP_RE.search(text)
        if match:
            current, total = int(match.group(1)), int(match.group(2))
            if total > 0:
                self._progress_bar.setRange(0, total)
                self._progress_bar.setValue(current)
                return
        self._progress_bar.setRange(0, 0)
