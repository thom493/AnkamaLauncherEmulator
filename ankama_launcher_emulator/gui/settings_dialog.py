"""Settings dialog with debug mode and troubleshooting tools."""

import logging
import os
import subprocess
import sys
import webbrowser

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QApplication,
    QDialog,
    QHBoxLayout,
    QVBoxLayout,
    QWidget,
)
from qfluentwidgets import (
    BodyLabel,
    CaptionLabel,
    CardWidget,
    InfoBar,
    InfoBarPosition,
    PrimaryPushButton,
    PushButton,
    SwitchButton,
    TitleLabel,
)

from ankama_launcher_emulator.consts import (
    CYTRUS_INSTALLED,
    DOFUS_INSTALLED,
    RETRO_INSTALLED,
    app_config_dir,
)
from ankama_launcher_emulator.gui.consts import (
    BORDER_HEXA,
    ORANGE_HEXA,
    PANEL_ALT_HEXA,
    PANEL_BG_HEXA,
    TEXT_MUTED_HEXA,
)
from ankama_launcher_emulator.gui.style import apply_dark_dialog_style
from ankama_launcher_emulator.haapi.account_meta import AccountMeta
from ankama_launcher_emulator.utils.app_config import (
    get_check_for_updates,
    get_debug_mode,
    get_last_selected_game,
    set_check_for_updates,
    set_debug_mode,
)
from ankama_launcher_emulator.utils.proxy_store import ProxyStore
from ankama_launcher_emulator.utils.updater import check_for_update, _current_version

logger = logging.getLogger()

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


def _open_folder(path: str) -> None:
    """Open a folder in the OS file manager."""
    if sys.platform == "win32":
        os.startfile(path)
    elif sys.platform == "darwin":
        subprocess.run(["open", path])
    else:
        subprocess.run(["xdg-open", path])


def _build_diagnostics() -> dict[str, str]:
    """Gather privacy-safe system diagnostics."""
    try:
        account_count = str(len(AccountMeta().all_entries()))
    except Exception:
        account_count = "?"

    try:
        proxy_count = str(len(ProxyStore().list_proxies()))
    except Exception:
        proxy_count = "?"

    return {
        "Platform": sys.platform,
        "Python": (
            f"{sys.version_info.major}.{sys.version_info.minor}"
            f".{sys.version_info.micro}"
        ),
        "Version": _current_version(),
        "Dofus3": "Yes" if DOFUS_INSTALLED else "No",
        "Retro": "Yes" if RETRO_INSTALLED else "No",
        "Cytrus": "Yes" if CYTRUS_INSTALLED else "No",
        "Accounts": account_count,
        "Proxies": proxy_count,
        "Debug mode": "Enabled" if get_debug_mode() else "Disabled",
        "Last game": get_last_selected_game() or "—",
    }


def _diagnostics_text() -> str:
    lines = ["AnkamaLauncherEmulator Diagnostics", "=" * 38]
    for key, value in _build_diagnostics().items():
        lines.append(f"{key:<13} {value}")
    return "\n".join(lines)


class _DiagRow(QWidget):
    """Single key/value row in the diagnostics preview."""

    def __init__(self, key: str, value: str, parent=None):
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 2, 0, 2)
        layout.setSpacing(8)

        key_label = CaptionLabel(f"{key}:")
        key_label.setStyleSheet(f"color: {TEXT_MUTED_HEXA};")
        layout.addWidget(key_label)

        val_label = BodyLabel(value)
        layout.addWidget(val_label)
        layout.addStretch()


class SettingsDialog(QDialog):
    """Application settings dialog."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Settings")
        self.setMinimumSize(420, 360)
        apply_dark_dialog_style(self)
        self._setup_ui()

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setSpacing(14)
        layout.setContentsMargins(18, 18, 18, 18)

        layout.addWidget(TitleLabel("Settings"))

        # Debug mode card
        debug_card = CardWidget()
        debug_card.setStyleSheet(
            "CardWidget {"
            f"background-color: {PANEL_BG_HEXA};"
            f"border: 1px solid {BORDER_HEXA};"
            "border-radius: 14px;"
            "}"
        )
        debug_layout = QHBoxLayout(debug_card)
        debug_layout.setContentsMargins(14, 10, 14, 10)
        debug_layout.setSpacing(12)

        debug_text_layout = QVBoxLayout()
        debug_text_layout.setSpacing(2)
        debug_title = BodyLabel("Debug Mode")
        debug_desc = CaptionLabel(
            "Enable verbose terminal output and write debug logs to ankalt_debug.log"
        )
        debug_desc.setWordWrap(True)
        debug_text_layout.addWidget(debug_title)
        debug_text_layout.addWidget(debug_desc)
        debug_layout.addLayout(debug_text_layout, 1)

        self._debug_switch = SwitchButton()
        self._debug_switch.setChecked(get_debug_mode())
        self._debug_switch.checkedChanged.connect(self._on_debug_toggled)
        debug_layout.addWidget(self._debug_switch)

        layout.addWidget(debug_card)

        # Update settings card
        update_card = CardWidget()
        update_card.setStyleSheet(debug_card.styleSheet())
        update_layout = QVBoxLayout(update_card)
        update_layout.setContentsMargins(14, 10, 14, 10)
        update_layout.setSpacing(8)

        update_title = BodyLabel("Updates")
        update_layout.addWidget(update_title)

        update_toggle_row = QHBoxLayout()
        update_toggle_row.setSpacing(12)

        update_toggle_text = QVBoxLayout()
        update_toggle_text.setSpacing(2)
        update_toggle_title = BodyLabel("Check for updates at startup")
        update_toggle_desc = CaptionLabel(
            "Notify when a new version is available on GitHub"
        )
        update_toggle_desc.setWordWrap(True)
        update_toggle_text.addWidget(update_toggle_title)
        update_toggle_text.addWidget(update_toggle_desc)
        update_toggle_row.addLayout(update_toggle_text, 1)

        self._update_switch = SwitchButton()
        self._update_switch.setChecked(get_check_for_updates())
        self._update_switch.checkedChanged.connect(self._on_update_toggled)
        update_toggle_row.addWidget(self._update_switch)
        update_layout.addLayout(update_toggle_row)

        check_now_row = QHBoxLayout()
        check_now_row.setSpacing(8)
        check_now_row.addStretch()

        self._check_now_btn = PushButton("Check Now")
        self._check_now_btn.setFixedHeight(CONTROL_HEIGHT)
        self._check_now_btn.setStyleSheet(_compact_control_style())
        self._check_now_btn.clicked.connect(self._on_check_now)
        check_now_row.addWidget(self._check_now_btn)
        update_layout.addLayout(check_now_row)

        layout.addWidget(update_card)

        # Troubleshooting card
        trouble_card = CardWidget()
        trouble_card.setStyleSheet(debug_card.styleSheet())
        trouble_layout = QVBoxLayout(trouble_card)
        trouble_layout.setContentsMargins(14, 10, 14, 10)
        trouble_layout.setSpacing(8)

        trouble_title = BodyLabel("Troubleshooting")
        trouble_layout.addWidget(trouble_title)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)

        open_btn = PushButton("Open Log Folder")
        open_btn.setFixedHeight(CONTROL_HEIGHT)
        open_btn.setStyleSheet(_compact_control_style())
        open_btn.clicked.connect(self._open_log_folder)
        btn_row.addWidget(open_btn)

        copy_btn = PrimaryPushButton("Copy Diagnostics")
        copy_btn.setFixedHeight(CONTROL_HEIGHT)
        copy_btn.setStyleSheet(_compact_control_style("PrimaryPushButton"))
        copy_btn.clicked.connect(self._copy_diagnostics)
        btn_row.addWidget(copy_btn)

        clear_btn = PushButton("Clear Logs")
        clear_btn.setFixedHeight(CONTROL_HEIGHT)
        clear_btn.setStyleSheet(_compact_control_style())
        clear_btn.clicked.connect(self._clear_logs)
        btn_row.addWidget(clear_btn)

        trouble_layout.addLayout(btn_row)
        layout.addWidget(trouble_card)

        # Diagnostics preview card
        diag_card = CardWidget()
        diag_card.setStyleSheet(debug_card.styleSheet())
        diag_layout = QVBoxLayout(diag_card)
        diag_layout.setContentsMargins(14, 10, 14, 10)
        diag_layout.setSpacing(4)

        diag_title = BodyLabel("System Info")
        diag_layout.addWidget(diag_title)

        for key, value in _build_diagnostics().items():
            diag_layout.addWidget(_DiagRow(key, value))

        layout.addWidget(diag_card)
        layout.addStretch()

        # Close button
        close_btn = PushButton("Close")
        close_btn.setFixedHeight(CONTROL_HEIGHT)
        close_btn.setStyleSheet(_compact_control_style())
        close_btn.clicked.connect(self.accept)
        layout.addWidget(close_btn, alignment=Qt.AlignmentFlag.AlignRight)

    def _on_debug_toggled(self, enabled: bool) -> None:
        set_debug_mode(enabled)
        _configure_logging_for_debug(enabled)
        logger.info("[SETTINGS] Debug mode %s", "enabled" if enabled else "disabled")

    def _on_update_toggled(self, enabled: bool) -> None:
        set_check_for_updates(enabled)
        logger.info("[SETTINGS] Check for updates %s", "enabled" if enabled else "disabled")

    def _on_check_now(self) -> None:
        self._check_now_btn.setEnabled(False)

        def task(_on_progress: object) -> dict | None:
            return check_for_update()  # type: ignore[return-value]

        def on_success(result: object) -> None:
            self._check_now_btn.setEnabled(True)
            info = result
            if info is not None:
                InfoBar.success(
                    "",
                    f"AnkAlt v{info['version']} is available.",  # type: ignore[index]
                    duration=5000,
                    position=InfoBarPosition.TOP_RIGHT,
                    parent=self,
                )
            else:
                InfoBar.info(
                    "",
                    "You are on the latest version.",
                    duration=3000,
                    position=InfoBarPosition.TOP_RIGHT,
                    parent=self,
                )

        def on_error(_err: object) -> None:
            self._check_now_btn.setEnabled(True)
            InfoBar.error(
                "",
                "Could not check for updates.",
                duration=4000,
                position=InfoBarPosition.TOP_RIGHT,
                parent=self,
            )

        from ankama_launcher_emulator.gui.utils import run_in_background

        run_in_background(task, on_success=on_success, on_error=on_error, parent=self)

    def _open_log_folder(self) -> None:
        try:
            _open_folder(app_config_dir)
        except Exception as exc:
            logger.warning("[SETTINGS] Failed to open log folder: %s", exc)

    def _copy_diagnostics(self) -> None:
        text = _diagnostics_text()
        clipboard = QApplication.clipboard()
        if clipboard is not None:
            clipboard.setText(text)
        logger.info("[SETTINGS] Diagnostics copied to clipboard")

    def _clear_logs(self) -> None:
        log_path = os.path.join(app_config_dir, "ankalt_debug.log")
        try:
            if os.path.exists(log_path):
                os.remove(log_path)
                logger.info("[SETTINGS] Debug log cleared")
            else:
                logger.info("[SETTINGS] No debug log to clear")
        except OSError as exc:
            logger.warning("[SETTINGS] Failed to clear debug log: %s", exc)


def _configure_logging_for_debug(enabled: bool) -> None:
    """Reconfigure root logger handlers based on debug mode."""
    root = logging.getLogger()
    for handler in root.handlers:
        if isinstance(handler, logging.StreamHandler) and not isinstance(
            handler, logging.FileHandler
        ):
            handler.setLevel(logging.DEBUG if enabled else logging.INFO)

    has_file_handler = any(
        isinstance(h, logging.FileHandler) for h in root.handlers
    )

    if enabled and not has_file_handler:
        _log_path = os.path.join(app_config_dir, "ankalt_debug.log")
        fh = logging.FileHandler(_log_path, mode="a", encoding="utf-8")
        fh.setLevel(logging.DEBUG)
        _fmt = logging.Formatter("%(asctime)s %(levelname)s [%(name)s] %(message)s")
        fh.setFormatter(_fmt)
        root.addHandler(fh)
        logger.info("[SETTINGS] Debug log file created: %s", _log_path)
    elif not enabled and has_file_handler:
        for handler in root.handlers[:]:
            if isinstance(handler, logging.FileHandler):
                handler.close()
                root.removeHandler(handler)
        logger.info("[SETTINGS] Debug log file removed")
