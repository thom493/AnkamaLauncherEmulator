from PyQt6.QtWidgets import QDialog, QFileDialog, QGridLayout, QHBoxLayout, QVBoxLayout
from qfluentwidgets import (
    BodyLabel,
    CardWidget,
    CaptionLabel,
    LineEdit,
    PasswordLineEdit,
    PrimaryPushButton,
    PushButton,
)

from ankama_launcher_emulator.gui.style import (
    apply_dark_dialog_style,
    compact_secondary_button_style,
)
from ankama_launcher_emulator.haapi.portable_exchange import (
    PortableAccountPayload,
    PortableExchangeError,
    inspect_portable_account,
)


class PortableAccountExportDialog(QDialog):
    def __init__(
        self,
        *,
        login: str,
        alias: str | None,
        has_proxy: bool,
        has_certificate: bool,
        parent=None,
    ):
        super().__init__(parent)
        self._login = login
        self._alias = alias
        self._has_proxy = has_proxy
        self._has_certificate = has_certificate
        self.setWindowTitle("Export Portable Account")
        self.setMinimumWidth(560)
        apply_dark_dialog_style(self)
        self._setup_ui()

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setSpacing(14)
        layout.setContentsMargins(20, 20, 20, 20)

        summary_card = CardWidget(self)
        summary_card.setObjectName("dialogSection")
        summary_layout = QVBoxLayout(summary_card)
        summary_layout.setContentsMargins(16, 16, 16, 16)
        summary_layout.setSpacing(10)
        summary_layout.addWidget(BodyLabel("Portable account bundle"))
        helper = CaptionLabel(
            "Export one encrypted account file. Anyone with file and passphrase can import it."
        )
        helper.setWordWrap(True)
        summary_layout.addWidget(helper)

        grid = QGridLayout()
        grid.setHorizontalSpacing(18)
        grid.setVerticalSpacing(6)
        grid.addWidget(CaptionLabel("Login"), 0, 0)
        grid.addWidget(BodyLabel(self._login), 0, 1)
        grid.addWidget(CaptionLabel("Alias"), 1, 0)
        grid.addWidget(BodyLabel(self._alias or "None"), 1, 1)
        grid.addWidget(CaptionLabel("Proxy included"), 2, 0)
        grid.addWidget(BodyLabel("Yes" if self._has_proxy else "No"), 2, 1)
        grid.addWidget(CaptionLabel("Certificate included"), 3, 0)
        grid.addWidget(BodyLabel("Yes" if self._has_certificate else "No"), 3, 1)
        summary_layout.addLayout(grid)
        layout.addWidget(summary_card)

        form_card = CardWidget(self)
        form_card.setObjectName("dialogSection")
        form_layout = QVBoxLayout(form_card)
        form_layout.setContentsMargins(16, 16, 16, 16)
        form_layout.setSpacing(12)

        form_layout.addWidget(BodyLabel("Destination file"))
        path_row = QHBoxLayout()
        self._path_input = LineEdit()
        self._path_input.setPlaceholderText("Portable account file")
        self._path_input.setText(f"{self._login}.ankalt-account")
        path_row.addWidget(self._path_input, 1)
        browse_btn = PushButton("Browse")
        browse_btn.setStyleSheet(compact_secondary_button_style())
        browse_btn.clicked.connect(self._browse_output_path)
        path_row.addWidget(browse_btn)
        form_layout.addLayout(path_row)

        form_layout.addWidget(BodyLabel("Passphrase"))
        self._passphrase_input = PasswordLineEdit()
        self._passphrase_input.setPlaceholderText("Passphrase")
        form_layout.addWidget(self._passphrase_input)

        form_layout.addWidget(BodyLabel("Confirm passphrase"))
        self._confirm_input = PasswordLineEdit()
        self._confirm_input.setPlaceholderText("Confirm passphrase")
        form_layout.addWidget(self._confirm_input)

        self._status_label = CaptionLabel("")
        self._status_label.setWordWrap(True)
        form_layout.addWidget(self._status_label)

        btn_row = QHBoxLayout()
        btn_row.addStretch(1)
        export_btn = PrimaryPushButton("Export File")
        export_btn.clicked.connect(self._on_accept)
        btn_row.addWidget(export_btn)
        cancel_btn = PushButton("Cancel")
        cancel_btn.setStyleSheet(compact_secondary_button_style())
        cancel_btn.clicked.connect(self.reject)
        btn_row.addWidget(cancel_btn)
        form_layout.addLayout(btn_row)
        layout.addWidget(form_card)

    def _browse_output_path(self) -> None:
        login = self.selected_login()
        suggested = f"{login}.ankalt-account" if login else "portable-account.ankalt-account"
        path, _ = QFileDialog.getSaveFileName(
            self,
            "Export Portable Account",
            suggested,
            "Portable Account (*.ankalt-account);;All Files (*)",
        )
        if path:
            self._path_input.setText(path)

    def _on_accept(self) -> None:
        if not self.output_path():
            self._status_label.setText("Destination file is required")
            return
        if not self.passphrase():
            self._status_label.setText("Passphrase is required")
            return
        if self.passphrase() != self._confirm_input.text():
            self._status_label.setText("Passphrases do not match")
            return
        self.accept()

    def selected_login(self) -> str:
        return self._login

    def output_path(self) -> str:
        return self._path_input.text().strip()

    def passphrase(self) -> str:
        return self._passphrase_input.text()


class PortableAccountImportDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Import Portable Account")
        self.setMinimumWidth(560)
        self._preview_payload: PortableAccountPayload | None = None
        apply_dark_dialog_style(self)
        self._setup_ui()

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setSpacing(14)
        layout.setContentsMargins(20, 20, 20, 20)

        summary_card = CardWidget(self)
        summary_card.setObjectName("dialogSection")
        summary_layout = QVBoxLayout(summary_card)
        summary_layout.setContentsMargins(16, 16, 16, 16)
        summary_layout.setSpacing(10)
        summary_layout.addWidget(BodyLabel("Portable account preview"))
        self._summary_caption = CaptionLabel(
            "Choose a file, enter passphrase, then preview account details before importing."
        )
        self._summary_caption.setWordWrap(True)
        summary_layout.addWidget(self._summary_caption)

        grid = QGridLayout()
        grid.setHorizontalSpacing(18)
        grid.setVerticalSpacing(6)
        grid.addWidget(CaptionLabel("Login"), 0, 0)
        self._preview_login = BodyLabel("—")
        grid.addWidget(self._preview_login, 0, 1)
        grid.addWidget(CaptionLabel("Alias"), 1, 0)
        self._preview_alias = BodyLabel("—")
        grid.addWidget(self._preview_alias, 1, 1)
        grid.addWidget(CaptionLabel("Proxy included"), 2, 0)
        self._preview_proxy = BodyLabel("—")
        grid.addWidget(self._preview_proxy, 2, 1)
        grid.addWidget(CaptionLabel("Certificate included"), 3, 0)
        self._preview_certificate = BodyLabel("—")
        grid.addWidget(self._preview_certificate, 3, 1)
        summary_layout.addLayout(grid)
        layout.addWidget(summary_card)

        form_card = CardWidget(self)
        form_card.setObjectName("dialogSection")
        form_layout = QVBoxLayout(form_card)
        form_layout.setContentsMargins(16, 16, 16, 16)
        form_layout.setSpacing(12)

        form_layout.addWidget(BodyLabel("Portable account file"))
        path_row = QHBoxLayout()
        self._path_input = LineEdit()
        self._path_input.setPlaceholderText("Portable account file")
        self._path_input.textChanged.connect(self._reset_preview)
        path_row.addWidget(self._path_input, 1)
        browse_btn = PushButton("Browse")
        browse_btn.setStyleSheet(compact_secondary_button_style())
        browse_btn.clicked.connect(self._browse_input_path)
        path_row.addWidget(browse_btn)
        form_layout.addLayout(path_row)

        form_layout.addWidget(BodyLabel("Passphrase"))
        self._passphrase_input = PasswordLineEdit()
        self._passphrase_input.setPlaceholderText("Passphrase")
        self._passphrase_input.textChanged.connect(self._reset_preview)
        form_layout.addWidget(self._passphrase_input)

        self._status_label = CaptionLabel("")
        self._status_label.setWordWrap(True)
        form_layout.addWidget(self._status_label)

        btn_row = QHBoxLayout()
        btn_row.addStretch(1)
        self._preview_btn = PushButton("Preview")
        self._preview_btn.setStyleSheet(compact_secondary_button_style())
        self._preview_btn.clicked.connect(self._on_preview)
        btn_row.addWidget(self._preview_btn)
        self._import_btn = PrimaryPushButton("Import Account")
        self._import_btn.setEnabled(False)
        self._import_btn.clicked.connect(self._on_accept)
        btn_row.addWidget(self._import_btn)
        cancel_btn = PushButton("Cancel")
        cancel_btn.setStyleSheet(compact_secondary_button_style())
        cancel_btn.clicked.connect(self.reject)
        btn_row.addWidget(cancel_btn)
        form_layout.addLayout(btn_row)
        layout.addWidget(form_card)

    def _browse_input_path(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Import Portable Account",
            "",
            "Portable Account (*.ankalt-account);;All Files (*)",
        )
        if path:
            self._path_input.setText(path)

    def _reset_preview(self) -> None:
        self._preview_payload = None
        self._import_btn.setEnabled(False)
        self._summary_caption.setText(
            "Choose a file, enter passphrase, then preview account details before importing."
        )
        self._preview_login.setText("—")
        self._preview_alias.setText("—")
        self._preview_proxy.setText("—")
        self._preview_certificate.setText("—")
        self._status_label.setText("")

    def _on_preview(self) -> None:
        if not self.input_path():
            self._status_label.setText("Portable account file is required")
            return
        if not self.passphrase():
            self._status_label.setText("Passphrase is required")
            return
        try:
            payload = inspect_portable_account(self.input_path(), self.passphrase())
        except PortableExchangeError as err:
            self._preview_payload = None
            self._import_btn.setEnabled(False)
            self._summary_caption.setText(
                "Choose a file, enter passphrase, then preview account details before importing."
            )
            self._preview_login.setText("—")
            self._preview_alias.setText("—")
            self._preview_proxy.setText("—")
            self._preview_certificate.setText("—")
            self._status_label.setText(str(err))
            return

        self._preview_payload = payload
        self._summary_caption.setText(
            "Preview ready. If details match expectation, import this account into launcher."
        )
        self._preview_login.setText(payload["login"])
        self._preview_alias.setText(payload.get("alias") or "None")
        self._preview_proxy.setText("Yes" if payload.get("proxy_url") else "No")
        self._preview_certificate.setText(
            "Yes" if payload.get("certificate") else "No"
        )
        self._status_label.setText("Preview ready")
        self._import_btn.setEnabled(True)

    def _on_accept(self) -> None:
        if self._preview_payload is None:
            self._status_label.setText("Preview file before importing")
            return
        self.accept()

    def input_path(self) -> str:
        return self._path_input.text().strip()

    def passphrase(self) -> str:
        return self._passphrase_input.text()

    def preview_payload(self) -> PortableAccountPayload | None:
        return self._preview_payload
