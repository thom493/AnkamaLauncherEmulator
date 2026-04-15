import os
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from ankama_launcher_emulator.gui.account_card import AccountCard
from ankama_launcher_emulator.gui.download_banner import DownloadBanner
from ankama_launcher_emulator.gui.main_window import MainWindow
from ankama_launcher_emulator.gui.app import APP_ICON_PATH, ensure_app, set_app_icon


class _DummyServer:
    def launch_dofus(self, *args, **kwargs):
        return 1234

    def launch_retro(self, *args, **kwargs):
        return 4321


class _StubProxyStore:
    def list_proxies(self):
        return {}

    def get_assignment(self, _login):
        return None

    def assign_proxy(self, _login, _proxy_id):
        return None

    def test_proxy(self, _proxy_id):
        return None


class GuiShellTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = ensure_app()

    def test_set_app_icon_uses_resources_ico(self):
        self.assertEqual(APP_ICON_PATH.name, "app.ico")
        self.assertTrue(APP_ICON_PATH.exists())
        set_app_icon(self.app)
        self.assertFalse(self.app.windowIcon().isNull())

    def test_main_window_builds_dashboard_shell(self):
        window = MainWindow(
            _DummyServer(),
            [{"apikey": {"login": "demo@example.com"}}],
            {"10.0.0.2": ("Fiber", "203.0.113.10")},
        )
        window.show()
        self.app.processEvents()
        self.assertEqual(window.windowTitle(), "AnkAlt Launcher")
        self.assertTrue(window._sidebar.isVisible())
        self.assertTrue(window._top_bar.isVisible())
        self.assertTrue(hasattr(window, "_banner"))
        self.assertEqual(window._title_label.text(), "Dofus 3")
        self.assertEqual(window._dofus_selector.property("navRole"), "game")
        self.assertEqual(window._retro_selector.property("navRole"), "game")
        self.assertEqual(window._cards[0].login, "demo@example.com")

    def test_main_window_empty_state_panel_visible_without_accounts(self):
        window = MainWindow(_DummyServer(), [], {})
        window.show()
        self.app.processEvents()
        self.assertEqual(window._empty_state_card.objectName(), "emptyStateCard")
        self.assertIn("No account found", window._empty_state_label.text())
        self.assertTrue(window._empty_state_card.isVisible())

    def test_download_banner_hides_when_idle_and_tracks_progress(self):
        banner = DownloadBanner()
        banner.set_status("Downloading update... 2 / 5")
        self.assertEqual(banner.objectName(), "statusStrip")
        self.assertTrue(banner.isVisible())
        self.assertEqual(banner._progress_bar.maximum(), 5)
        self.assertEqual(banner._progress_bar.value(), 2)
        banner.set_status("")
        self.assertFalse(banner.isVisible())

    def test_account_card_keeps_all_main_controls_visible(self):
        card = AccountCard(
            "demo@example.com",
            {"10.0.0.2": ("Fiber", "203.0.113.10")},
            proxy_store=_StubProxyStore(),
        )
        self.assertEqual(card._login_label.text(), "demo@example.com")
        self.assertEqual(card._launch_btn.text(), "Launch")
        self.assertEqual(card._test_proxy_btn.text(), "Test")
        self.assertEqual(card._ip_combo.count(), 2)
        self.assertEqual(card._proxy_combo.count(), 1)
        self.assertTrue(card._status_dot.isHidden())

    def test_main_spec_references_app_icon(self):
        spec_text = Path("main.spec").read_text(encoding="utf-8")
        self.assertIn("icon='resources/app.ico'", spec_text)
        self.assertIn("name='AnkAlt Launcher'", spec_text)

    def test_windows_workflow_uses_ankalt_launcher_binary(self):
        workflow_text = Path(".github/workflows/build-windows.yml").read_text(
            encoding="utf-8"
        )
        self.assertIn("name: AnkAlt-Launcher-windows", workflow_text)
        self.assertIn("path: dist/AnkAlt Launcher.exe", workflow_text)
