import json
import os
import tempfile
import unittest
from pathlib import Path
from typing import cast
from unittest.mock import MagicMock, call, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtCore import Qt
from qfluentwidgets import PushButton

from ankama_launcher_emulator.gui.account_card import AccountCard
from ankama_launcher_emulator.gui.download_banner import DownloadBanner
from ankama_launcher_emulator.gui.main_window import MainWindow
from ankama_launcher_emulator.gui.app import APP_ICON_PATH, ensure_app, set_app_icon
from ankama_launcher_emulator.server.server import AnkamaLauncherServer
from ankama_launcher_emulator.utils.proxy_store import ProxyStore


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

    def get_proxy_url(self, _login):
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
        with patch(
            "ankama_launcher_emulator.gui.account_card.has_active_credentials",
            return_value=True,
        ):
            window = MainWindow(
                cast(AnkamaLauncherServer, _DummyServer()),
                [{"apikey": {"login": "demo@example.com"}}],
                {"10.0.0.2": ("Fiber", "203.0.113.10")},
            )
        window.show()
        self.app.processEvents()
        self.assertEqual(window.windowTitle(), "AnkAlt Launcher")
        self.assertTrue(window._sidebar.isVisible())
        self.assertTrue(window._top_bar.isVisible())
        self.assertTrue(hasattr(window, "_banner"))
        self.assertIs(window._banner.parent(), window._top_bar)
        self.assertFalse(window._selected_game_logo.pixmap().isNull())
        self.assertEqual(
            window._accounts_scroll.verticalScrollBarPolicy(),
            Qt.ScrollBarPolicy.ScrollBarAsNeeded,
        )
        self.assertEqual(window._title_label.text(), "Dofus 3")
        self.assertEqual(window._dofus_selector.property("navRole"), "game")
        self.assertEqual(window._retro_selector.property("navRole"), "game")
        self.assertEqual(window._cards[0].login, "demo@example.com")

    @patch("ankama_launcher_emulator.gui.main_window.RETRO_INSTALLED", True)
    @patch("ankama_launcher_emulator.gui.main_window.DOFUS_INSTALLED", True)
    @patch("ankama_launcher_emulator.gui.main_window.get_last_selected_game")
    def test_main_window_restores_saved_retro_selection(self, get_last_selected_game):
        get_last_selected_game.return_value = "retro"
        window = MainWindow(cast(AnkamaLauncherServer, _DummyServer()), [], {})
        window.show()
        self.app.processEvents()

        self.assertEqual(window._title_label.text(), "Dofus Rétro")
        self.assertFalse(window._current_game_is_dofus3)

    @patch("ankama_launcher_emulator.gui.main_window.RETRO_INSTALLED", False)
    @patch("ankama_launcher_emulator.gui.main_window.DOFUS_INSTALLED", True)
    @patch("ankama_launcher_emulator.gui.main_window.get_last_selected_game")
    def test_main_window_falls_back_when_saved_game_is_unavailable(
        self, get_last_selected_game
    ):
        get_last_selected_game.return_value = "retro"
        window = MainWindow(cast(AnkamaLauncherServer, _DummyServer()), [], {})
        window.show()
        self.app.processEvents()

        self.assertEqual(window._title_label.text(), "Dofus 3")
        self.assertTrue(window._current_game_is_dofus3)

    @patch("ankama_launcher_emulator.gui.main_window.set_last_selected_game")
    def test_main_window_persists_selected_game_tab(self, set_last_selected_game):
        window = MainWindow(cast(AnkamaLauncherServer, _DummyServer()), [], {})

        set_last_selected_game.reset_mock()
        window._select_game(False)
        window._select_game(True)

        self.assertEqual(
            set_last_selected_game.call_args_list,
            [call("retro"), call("dofus3")],
        )

    def test_main_window_empty_state_panel_visible_without_accounts(self):
        window = MainWindow(cast(AnkamaLauncherServer, _DummyServer()), [], {})
        window.show()
        self.app.processEvents()
        self.assertEqual(window._empty_state_card.objectName(), "emptyStateCard")
        self.assertIn("No account found", window._empty_state_label.text())
        self.assertTrue(window._empty_state_card.isVisible())

    def test_main_window_exposes_import_and_export_actions(self):
        with patch(
            "ankama_launcher_emulator.gui.account_card.has_active_credentials",
            return_value=True,
        ):
            window = MainWindow(
                cast(AnkamaLauncherServer, _DummyServer()),
                [{"apikey": {"login": "demo@example.com"}}],
                {},
            )
        buttons = {
            widget.text()
            for widget in window.findChildren(PushButton)
        }
        self.assertIn("Import", buttons)
        self.assertNotIn("Export", buttons)
        self.assertIn("Add Account", buttons)
        self.assertTrue(hasattr(window._cards[0], "_manage_btn"))

    def test_main_window_initial_refresh_updates_accounts_and_interfaces(self):
        with patch(
            "ankama_launcher_emulator.gui.account_card.has_active_credentials",
            return_value=True,
        ):
            window = MainWindow(
                cast(AnkamaLauncherServer, _DummyServer()),
                [],
                {},
                bootstrap_loading=True,
            )

            self.assertEqual(window._cards, [])
            self.assertEqual(window._interfaces, {})

            window._refresh_generation = 1
            window._apply_accounts_refresh(
                [{"apikey": {"login": "demo@example.com"}}],
                1,
            )
            window._apply_interfaces_refresh(
                {"10.0.0.2": ("Fiber", "203.0.113.10")},
                1,
            )

            self.assertFalse(window._bootstrap_loading)
            self.assertEqual(len(window._cards), 1)
            self.assertEqual(
                window._accounts[0]["apikey"]["login"], "demo@example.com"
            )
            self.assertEqual(
                window._interfaces, {"10.0.0.2": ("Fiber", "203.0.113.10")}
            )
            self.assertEqual(window._cards[0]._ip_combo.count(), 2)

    def test_main_window_interfaces_first_still_populates_new_cards(self):
        with patch(
            "ankama_launcher_emulator.gui.account_card.has_active_credentials",
            return_value=True,
        ):
            window = MainWindow(
                cast(AnkamaLauncherServer, _DummyServer()),
                [],
                {},
                bootstrap_loading=True,
            )

            window._refresh_generation = 1
            window._apply_interfaces_refresh(
                {"10.0.0.2": ("Fiber", "203.0.113.10")},
                1,
            )
            window._apply_accounts_refresh(
                [{"apikey": {"login": "demo@example.com"}}],
                1,
            )

            self.assertEqual(len(window._cards), 1)
            self.assertEqual(window._cards[0]._ip_combo.count(), 2)
            self.assertEqual(
                window._interfaces, {"10.0.0.2": ("Fiber", "203.0.113.10")}
            )

    @patch("ankama_launcher_emulator.gui.main_window.QTimer.singleShot")
    def test_main_window_start_initial_refresh_schedules_background_fetch(
        self, single_shot
    ):
        window = MainWindow(
            cast(AnkamaLauncherServer, _DummyServer()),
            [],
            {},
            bootstrap_loading=True,
        )

        window.start_initial_refresh()

        self.assertEqual(single_shot.call_count, 1)
        delay, callback = single_shot.call_args.args
        self.assertEqual(delay, 0)
        self.assertEqual(getattr(callback, "__self__", None), window)
        self.assertEqual(getattr(callback, "__name__", ""), "_schedule_refresh")

    @patch("ankama_launcher_emulator.gui.main_window.run_in_background")
    def test_main_window_schedule_refresh_starts_both_workers(
        self, run_in_background
    ):
        window = MainWindow(
            cast(AnkamaLauncherServer, _DummyServer()),
            [],
            {},
            bootstrap_loading=True,
        )

        window._schedule_refresh()

        self.assertEqual(run_in_background.call_count, 2)
        self.assertTrue(window._is_refreshing_accounts)
        self.assertTrue(window._is_refreshing_interfaces)
        self.assertEqual(window._refresh_generation, 1)

    @patch("ankama_launcher_emulator.gui.main_window.run_in_background")
    def test_main_window_account_refresh_error_clears_bootstrap_loading(
        self, run_in_background
    ):
        window = MainWindow(
            cast(AnkamaLauncherServer, _DummyServer()),
            [],
            {},
            bootstrap_loading=True,
        )

        def fail_fetch(_task, on_success=None, on_error=None, **_kwargs):
            del on_success
            assert on_error is not None
            on_error(RuntimeError("boom"))

        run_in_background.side_effect = fail_fetch

        window._schedule_accounts_refresh(1)

        self.assertFalse(window._is_refreshing_accounts)
        self.assertFalse(window._bootstrap_loading)
        self.assertIn("No account found", window._empty_state_label.text())

    def test_main_window_discards_stale_interface_results(self):
        window = MainWindow(
            cast(AnkamaLauncherServer, _DummyServer()),
            [],
            {},
        )

        window._refresh_generation = 2
        window._interfaces = {"10.0.0.5": ("Old", "198.51.100.5")}
        window._apply_interfaces_refresh({"10.0.0.2": ("New", "203.0.113.10")}, 1)

        self.assertEqual(
            window._interfaces, {"10.0.0.5": ("Old", "198.51.100.5")}
        )

    def test_download_banner_hides_when_idle_and_tracks_progress(self):
        banner = DownloadBanner()
        banner.set_status("Downloading update... 2 / 5")
        self.assertEqual(banner.objectName(), "statusStrip")
        self.assertTrue(banner.isVisible())
        self.assertIsNotNone(banner._loading_label.movie())
        self.assertTrue(banner._loading_movie.isValid())
        self.assertEqual(banner._progress_bar.maximum(), 5)
        self.assertEqual(banner._progress_bar.value(), 2)
        self.assertEqual(banner._progress_label.text(), "Downloading update...")
        self.assertNotIn("2 / 5", banner._progress_label.text())
        banner.set_status("")
        self.assertFalse(banner.isVisible())

    def test_account_card_keeps_all_main_controls_visible(self):
        with patch(
            "ankama_launcher_emulator.gui.account_card.has_active_credentials",
            return_value=True,
        ):
            card = AccountCard(
                "demo@example.com",
                {"10.0.0.2": ("Fiber", "203.0.113.10")},
                proxy_store=cast(ProxyStore, _StubProxyStore()),
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
        self.assertIn("('resources/load.gif', 'resources')", spec_text)

    def test_windows_workflow_uses_ankalt_launcher_binary(self):
        workflow_text = Path(".github/workflows/build-windows.yml").read_text(
            encoding="utf-8"
        )
        self.assertIn("name: AnkAlt-Launcher-windows", workflow_text)
        self.assertIn("path: dist/AnkAlt Launcher.exe", workflow_text)

    def test_app_config_returns_none_for_corrupt_or_invalid_saved_game(self):
        from ankama_launcher_emulator.utils import app_config

        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = os.path.join(tmpdir, "config.json")

            with open(config_path, "w", encoding="utf-8") as file:
                file.write("{")
            with patch.object(app_config, "APP_CONFIG_PATH", config_path):
                self.assertIsNone(app_config.get_last_selected_game())

            with open(config_path, "w", encoding="utf-8") as file:
                json.dump({"last_selected_game": "wakfu"}, file)
            with patch.object(app_config, "APP_CONFIG_PATH", config_path):
                self.assertIsNone(app_config.get_last_selected_game())

    def test_app_config_persists_last_selected_game(self):
        from ankama_launcher_emulator.utils import app_config

        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = os.path.join(tmpdir, "config.json")

            with patch.object(app_config, "APP_CONFIG_PATH", config_path):
                app_config.set_last_selected_game("retro")
                self.assertEqual(app_config.get_last_selected_game(), "retro")

            with open(config_path, "r", encoding="utf-8") as file:
                config = json.load(file)
            self.assertEqual(config["last_selected_game"], "retro")

    @patch("ankama_launcher_emulator.gui.app.sys.exit")
    @patch("ankama_launcher_emulator.gui.app.set_app_icon")
    @patch("ankama_launcher_emulator.gui.app.ensure_app")
    @patch("ankama_launcher_emulator.gui.app.MainWindow")
    @patch("ankama_launcher_emulator.gui.app.AnkamaLauncherServer")
    @patch("ankama_launcher_emulator.gui.app.AnkamaLauncherHandler")
    def test_run_gui_shows_window_before_loading_data(
        self,
        handler_cls,
        server_cls,
        main_window_cls,
        ensure_app,
        set_app_icon,
        sys_exit,
    ):
        app = MagicMock()
        app.exec.return_value = 0
        ensure_app.return_value = app
        server = MagicMock()
        server_cls.return_value = server
        window = MagicMock()
        main_window_cls.return_value = window

        from ankama_launcher_emulator.gui.app import run_gui

        run_gui()

        server.start.assert_called_once_with()
        main_window_cls.assert_called_once_with(server, [], {}, bootstrap_loading=True)
        window.show.assert_called_once_with()
        window.start_initial_refresh.assert_called_once_with()
        set_app_icon.assert_called_once_with(app)
        sys_exit.assert_called_once_with(0)
