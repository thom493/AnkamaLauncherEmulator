import sys

from PyQt6.QtGui import QIcon
from PyQt6.QtWidgets import (
    QApplication,
)
from qfluentwidgets import (
    Theme,
    setTheme,
)

from ankama_launcher_emulator.consts import RESOURCES
from ankama_launcher_emulator.gui.main_window import MainWindow
from ankama_launcher_emulator.haapi.account_persistence import list_all_api_keys
from ankama_launcher_emulator.server.handler import AnkamaLauncherHandler
from ankama_launcher_emulator.server.server import AnkamaLauncherServer
from ankama_launcher_emulator.utils.internet import get_available_network_interfaces

APP_ICON_PATH = RESOURCES / "app.ico"


def ensure_app() -> QApplication:
    app = QApplication.instance()
    if app is None:
        app = QApplication(sys.argv)
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
    setTheme(Theme.DARK)
    set_app_icon(app)

    window = MainWindow(server, accounts, interfaces)
    window.show()
    sys.exit(app.exec())
