import os
import unittest
from unittest.mock import MagicMock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from ankama_launcher_emulator.gui.add_account_dialog import AddAccountDialog
from ankama_launcher_emulator.gui.app import ensure_app
from ankama_launcher_emulator.gui.main_window import MainWindow
from ankama_launcher_emulator.haapi.haapi import Haapi
from ankama_launcher_emulator.haapi.shield import ShieldRecoveryRequired
from ankama_launcher_emulator.interfaces.account_game_info import AccountGameInfo
from ankama_launcher_emulator.server.handler import AnkamaLauncherHandler


class _DummyServer:
    def launch_dofus(self, *args, **kwargs):
        return 1234

    def launch_retro(self, *args, **kwargs):
        return 4321


class _ServerWithHandler(_DummyServer):
    def __init__(self):
        self.handler = AnkamaLauncherHandler()


class _ProxyStore:
    def list_proxies(self):
        return {}

    def get_proxy(self, _proxy_id):
        return None

    def get_assignment(self, _login):
        return None

    def assign_proxy(self, _login, _proxy_id):
        return None

    def save_validated(self, _login, _proxy_url):
        return None


class AuthFlowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = ensure_app()

    @patch("ankama_launcher_emulator.gui.add_account_dialog.run_in_background")
    def test_add_account_falls_back_to_browser_when_headless_pkce_is_blocked(
        self, run_in_background
    ):
        dialog = AddAccountDialog(_ProxyStore())
        dialog._login_input.setText("demo@example.com")
        dialog._password_input.setText("hunter2")

        def fail_headless(task, on_success=None, on_error=None, parent=None):
            del task, on_success, parent
            on_error(RuntimeError("Failed to extract CSRF state from login page"))

        run_in_background.side_effect = fail_headless

        with patch.object(dialog, "_start_browser_login") as start_browser_login:
            dialog._on_add()

        start_browser_login.assert_called_once_with(
            "demo@example.com", None, None
        )

    @patch("ankama_launcher_emulator.gui.add_account_dialog.run_in_background")
    @patch("ankama_launcher_emulator.gui.add_account_dialog._load_embedded_auth_dialog_class")
    def test_add_account_runtime_loader_failure_updates_status(
        self,
        load_embedded_auth_dialog_class,
        run_in_background,
    ):
        dialog = AddAccountDialog(_ProxyStore())
        dialog._login_input.setText("demo@example.com")
        dialog._password_input.setText("hunter2")

        load_embedded_auth_dialog_class.side_effect = ImportError("QWebEngine missing")

        def fail_headless(task, on_success=None, on_error=None, parent=None):
            del task, on_success, parent
            on_error(RuntimeError("Failed to extract CSRF state from login page"))

        run_in_background.side_effect = fail_headless

        dialog._on_add()

        self.assertEqual(
            dialog._status_label.text(),
            "Embedded auth dialog unavailable: QWebEngine missing",
        )
        self.assertTrue(dialog._add_btn.isEnabled())

    def test_main_window_wires_server_shield_recovery_callback(self):
        server = _ServerWithHandler()

        window = MainWindow(
            server,
            [{"apikey": {"login": "demo@example.com"}}],
            {},
        )

        self.assertTrue(callable(server.handler.on_shield_recovery))
        self.assertEqual(
            server.handler.on_shield_recovery.__self__,
            window,
        )

    @patch("ankama_launcher_emulator.gui.main_window.QTimer.singleShot")
    @patch.object(MainWindow, "_handle_shield_recovery")
    @patch.object(MainWindow, "_current_launch_fn")
    def test_server_shield_recovery_callback_routes_known_login_to_recovery_handler(
        self,
        current_launch_fn,
        handle_shield_recovery,
        single_shot,
    ):
        server = _ServerWithHandler()
        window = MainWindow(
            server,
            [{"apikey": {"login": "demo@example.com"}}],
            {},
        )
        launch = MagicMock()
        current_launch_fn.return_value = launch
        single_shot.side_effect = lambda _delay, callback: callback()

        window._on_server_shield_recovery("demo@example.com")

        err, routed_launch, card = handle_shield_recovery.call_args.args
        self.assertIsInstance(err, ShieldRecoveryRequired)
        self.assertEqual(err.login, "demo@example.com")
        self.assertIs(routed_launch, launch)
        self.assertEqual(card.login, "demo@example.com")

    def test_create_token_403_with_certificate_raises_shield_recovery_required(self):
        haapi = Haapi(
            "apikey",
            "demo@example.com",
            None,
            None,
        )
        haapi.zaap_session = MagicMock()
        response = MagicMock()
        response.status_code = 403
        haapi.zaap_session.get.return_value = response

        with patch(
            "ankama_launcher_emulator.haapi.haapi.CryptoHelper.generateHashFromCertif",
            return_value="cert-hash",
        ):
            with self.assertRaises(ShieldRecoveryRequired) as ctx:
                haapi.createToken(
                    102,
                    {"id": 42, "encodedCertificate": "abc", "login": "demo@example.com"},
                    hm1="hm1",
                    hm2="hm2",
                )

        self.assertEqual(ctx.exception.login, "demo@example.com")

    @patch("ankama_launcher_emulator.server.handler.AccountMeta")
    @patch("ankama_launcher_emulator.server.handler.CryptoHelper.getStoredCertificate")
    def test_auth_get_game_token_notifies_shield_recovery_callback(
        self,
        get_stored_certificate,
        account_meta,
    ):
        handler = AnkamaLauncherHandler()
        haapi = MagicMock()
        haapi.login = "demo@example.com"
        haapi.createToken.side_effect = ShieldRecoveryRequired("demo@example.com")
        handler.infos_by_hash["hash"] = AccountGameInfo(
            login="demo@example.com",
            game_id=102,
            api_key="apikey",
            haapi=haapi,
        )
        get_stored_certificate.side_effect = FileNotFoundError
        account_meta.return_value.get_hm1.return_value = "hm1"
        account_meta.return_value.get_hm2.return_value = "hm2"
        recovery_callback = MagicMock()
        handler.on_shield_recovery = recovery_callback

        with self.assertRaises(ShieldRecoveryRequired):
            handler.auth_getGameToken("hash", 102)

        recovery_callback.assert_called_once_with("demo@example.com")
        haapi.createToken.assert_called_once_with(
            102,
            None,
            hm1="hm1",
            hm2="hm2",
        )

    @patch("ankama_launcher_emulator.gui.main_window.run_in_background")
    @patch.object(MainWindow, "_handle_shield_recovery")
    def test_launch_handler_routes_shield_recovery_required(
        self,
        handle_shield_recovery,
        run_in_background,
    ):
        window = MainWindow(
            _DummyServer(),
            [{"apikey": {"login": "demo@example.com"}}],
            {},
        )
        card = MagicMock()
        handler = window._make_launch_handler("demo@example.com", card)

        def fail_launch(task, on_success=None, on_error=None, on_progress=None, parent=None):
            del task, on_success, on_progress, parent
            on_error(ShieldRecoveryRequired("demo@example.com"))

        run_in_background.side_effect = fail_launch

        handler(None, None)

        handle_shield_recovery.assert_called_once()

    @patch("ankama_launcher_emulator.gui.main_window.verify_proxy_ip")
    @patch("ankama_launcher_emulator.gui.main_window.build_proxy_listener")
    @patch.object(MainWindow, "_check_shield")
    def test_proxy_launch_does_not_force_oauth_refresh_before_create_token(
        self,
        check_shield,
        build_proxy_listener,
        verify_proxy_ip,
    ):
        proxy_listener = MagicMock()
        proxy_listener.start.return_value = 5555
        build_proxy_listener.return_value = (proxy_listener, "socks5://127.0.0.1:9050")

        window = MainWindow(
            _DummyServer(),
            [{"apikey": {"login": "demo@example.com"}}],
            {},
        )

        progress_updates = []
        pid = window._launch_dofus(
            "demo@example.com",
            interface_ip=None,
            proxy_url="socks5://127.0.0.1:9050",
            on_progress=progress_updates.append,
        )

        self.assertEqual(pid, 1234)
        verify_proxy_ip.assert_called_once_with("socks5://127.0.0.1:9050")
        check_shield.assert_called_once()
        self.assertEqual(progress_updates, ["Verifying proxy..."])
