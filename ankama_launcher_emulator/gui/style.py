from PyQt6.QtWidgets import QApplication, QDialog

from ankama_launcher_emulator.gui.consts import (
    APP_BG_HEXA,
    BORDER_HEXA,
    ORANGE_HEXA,
    PANEL_ALT_HEXA,
    PANEL_BG_HEXA,
    TEXT_HEXA,
    TEXT_MUTED_HEXA,
    TEXT_SOFT_HEXA,
)


_APP_STYLE_MARKER = "/* AnkAlt shared control style */"

APP_CONTROL_STYLESHEET = f"""
{_APP_STYLE_MARKER}
PushButton, PrimaryPushButton, ComboBox, LineEdit, PasswordLineEdit {{
    min-height: 28px;
    max-height: 28px;
    border-radius: 14px;
    padding: 2px 10px;
    color: {TEXT_HEXA};
}}

ComboBox {{
    padding-left: 10px;
    padding-right: 26px;
}}

ComboBoxMenu, RoundMenu {{
    border-radius: 14px;
}}

QListView#comboListWidget, ListWidget#comboListWidget {{
    border-radius: 14px;
    padding: 2px 0;
}}

QListView#comboListWidget::item, ListWidget#comboListWidget::item {{
    min-height: 26px;
    padding: 2px 10px;
}}

QComboBox QAbstractItemView, QListView#comboListWidget, ListWidget#comboListWidget {{
    background-color: {PANEL_ALT_HEXA};
    color: {TEXT_HEXA};
}}
"""


def apply_app_style(app: QApplication) -> None:
    current = app.styleSheet()
    if _APP_STYLE_MARKER in current:
        return

    separator = "\n" if current else ""
    app.setStyleSheet(f"{current}{separator}{APP_CONTROL_STYLESHEET}")


def compact_secondary_button_style(kind: str = "PushButton") -> str:
    return (
        f"{kind} {{"
        f"background-color: {PANEL_ALT_HEXA};"
        f"border: 1px solid {BORDER_HEXA};"
        "border-radius: 14px;"
        "padding: 2px 10px;"
        f"color: {TEXT_HEXA};"
        "}"
        f"{kind}:hover {{ border-color: {ORANGE_HEXA}; }}"
    )


def dialog_section_style() -> str:
    return (
        "CardWidget#dialogSection {"
        f"background-color: {PANEL_BG_HEXA};"
        f"border: 1px solid {BORDER_HEXA};"
        "border-radius: 16px;"
        "}"
    )


def apply_dark_dialog_style(dialog: QDialog) -> None:
    dialog.setStyleSheet(
        "QDialog {"
        f"background-color: {APP_BG_HEXA};"
        "}"
        f"QDialog BodyLabel {{ color: {TEXT_SOFT_HEXA}; }}"
        f"QDialog CaptionLabel {{ color: {TEXT_MUTED_HEXA}; }}"
        f"QDialog LineEdit, QDialog PasswordLineEdit, QDialog ComboBox {{"
        f"background-color: {PANEL_ALT_HEXA};"
        f"border: 1px solid {BORDER_HEXA};"
        "border-radius: 14px;"
        "padding: 2px 10px;"
        "}"
        f"QDialog PushButton, QDialog PrimaryPushButton {{ color: {TEXT_HEXA}; }}"
        f"{dialog_section_style()}"
    )
