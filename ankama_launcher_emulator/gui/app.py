import contextlib
import io
import sys
from typing import cast

from PyQt6.QtCore import Qt, QCoreApplication, qInstallMessageHandler
from PyQt6.QtGui import QIcon
from PyQt6.QtWidgets import (
    QApplication,
)

QCoreApplication.setAttribute(Qt.ApplicationAttribute.AA_ShareOpenGLContexts)

with contextlib.redirect_stdout(io.StringIO()):
    from qfluentwidgets import (
        Theme,
        setTheme,
        setThemeColor,
    )


def _qt_msg_filter(mode, ctx, msg):
    if "setPointSize: Point size <= 0" in msg:
        return
    sys.stderr.write(msg + "\n")


qInstallMessageHandler(_qt_msg_filter)

from ankama_launcher_emulator.consts import RESOURCES
from ankama_launcher_emulator.gui.consts import ORANGE_HEXA
from ankama_launcher_emulator.gui.main_window import MainWindow
from ankama_launcher_emulator.gui.style import apply_app_style
from ankama_launcher_emulator.haapi.account_persistence import list_all_api_keys
from ankama_launcher_emulator.server.handler import AnkamaLauncherHandler
from ankama_launcher_emulator.server.server import AnkamaLauncherServer
from ankama_launcher_emulator.utils.internet import get_available_network_interfaces

APP_ICON_PATH = RESOURCES / "app.ico"


def ensure_app() -> QApplication:
    app = QApplication.instance()
    if app is None:
        app = QApplication(sys.argv)
    app = cast(QApplication, app)
    app.setStyle("Fusion")
    setTheme(Theme.DARK)
    setThemeColor(ORANGE_HEXA)
    apply_app_style(app)
    return app


def set_app_icon(app: QApplication) -> None:
    if APP_ICON_PATH.exists():
        app.setWindowIcon(QIcon(str(APP_ICON_PATH)))


def run_gui() -> None:
    handler = AnkamaLauncherHandler()
    server = AnkamaLauncherServer(handler)
    server.start()

    accounts = list_all_api_keys()
    interfaces = get_available_network_interfaces()

    app = ensure_app()
    set_app_icon(app)

    window = MainWindow(server, accounts, interfaces)
    window.show()
    sys.exit(app.exec())
