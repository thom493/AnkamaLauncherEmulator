import os
import sys
import tempfile
import unittest
from unittest.mock import ANY, MagicMock, call, patch

import requests

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtWidgets import QDialog

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

    def get_proxy_url(self, _login):
        return None

    def assign_proxy(self, _login, _proxy_id):
        return None

    def save_validated(self, _login, _proxy_url):
        return None


# Patch applied at class level to avoid Mac Device.getOsVersion crash in all
# tests that need to instantiate AccountCard / MainWindow.
_patch_credentials = patch(
    "ankama_launcher_emulator.gui.account_card.has_active_credentials",
    return_value=False,
)


class AuthFlowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = ensure_app()

    def test_add_account_falls_back_to_browser_when_headless_pkce_is_blocked(self):
        dialog = AddAccountDialog(_ProxyStore())
        dialog._login_input.setText("demo@example.com")
        dialog._password_input.setText("hunter2")

        def fail_headless(task, on_success=None, on_error=None):
            del task, on_success
            on_error(RuntimeError("Failed to extract CSRF state from login page"))

        with patch.object(dialog, "_run_worker", side_effect=fail_headless):
            with patch.object(dialog, "_start_browser_login") as start_browser_login:
                dialog._on_add()

        start_browser_login.assert_called_once_with(
            "demo@example.com", None, None, True
        )

    @patch("ankama_launcher_emulator.gui.add_account_dialog._load_embedded_auth_dialog_class")
    def test_add_account_runtime_loader_failure_updates_status(
        self,
        load_embedded_auth_dialog_class,
    ):
        dialog = AddAccountDialog(_ProxyStore())
        dialog._login_input.setText("demo@example.com")
        dialog._password_input.setText("hunter2")

        load_embedded_auth_dialog_class.side_effect = ImportError("QWebEngine missing")

        def fail_headless(task, on_success=None, on_error=None):
            del task, on_success
            on_error(RuntimeError("Failed to extract CSRF state from login page"))

        with patch.object(dialog, "_run_worker", side_effect=fail_headless):
            dialog._on_add()

        self.assertEqual(
            dialog._status_label.text(),
            "Embedded auth dialog unavailable: QWebEngine missing",
        )
        self.assertTrue(dialog._add_btn.isEnabled())

    @_patch_credentials
    def test_main_window_wires_server_shield_recovery_callback(self, _creds):
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

    @_patch_credentials
    @patch("ankama_launcher_emulator.gui.main_window.QTimer.singleShot")
    @patch.object(MainWindow, "_handle_shield_light")
    @patch.object(MainWindow, "_current_launch_fn")
    def test_server_shield_recovery_callback_routes_known_login_to_shield_light(
        self,
        current_launch_fn,
        handle_shield_light,
        single_shot,
        _creds,
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

        login_arg, routed_launch, card = handle_shield_light.call_args.args
        self.assertEqual(login_arg, "demo@example.com")
        self.assertIs(routed_launch, launch)
        self.assertEqual(card.login, "demo@example.com")

    def test_shield_browser_dialog_shim_exports_embedded_dialog(self):
        from ankama_launcher_emulator.gui.embedded_auth_browser_dialog import (
            EmbeddedAuthBrowserDialog,
        )
        from ankama_launcher_emulator.gui.shield_browser_dialog import (
            ShieldBrowserDialog,
        )

        self.assertIs(ShieldBrowserDialog, EmbeddedAuthBrowserDialog)

    @patch("ankama_launcher_emulator.gui.add_account_dialog.importlib.import_module")
    def test_add_account_loader_imports_embedded_auth_browser_module(
        self,
        import_module,
    ):
        from ankama_launcher_emulator.gui.add_account_dialog import (
            _load_embedded_auth_dialog_class,
        )

        module = MagicMock()
        module.EmbeddedAuthBrowserDialog = object()
        import_module.return_value = module

        dialog_class = _load_embedded_auth_dialog_class()

        import_module.assert_called_once_with(
            "ankama_launcher_emulator.gui.embedded_auth_browser_dialog"
        )
        self.assertIs(dialog_class, module.EmbeddedAuthBrowserDialog)

    @unittest.skipUnless(sys.platform == "win32", "Device.getUUID/getOsVersion are Windows-only")
    @patch("ankama_launcher_emulator.gui.add_account_dialog.persist_managed_account")
    @patch("ankama_launcher_emulator.gui.add_account_dialog.store_shield_certificate")
    @patch("ankama_launcher_emulator.gui.add_account_dialog.validate_security_code")
    @patch("ankama_launcher_emulator.gui.add_account_dialog.ShieldCodeDialog")
    def test_add_account_shield_validation_persists_without_random_hm1(
        self,
        shield_dialog_cls,
        validate_security_code,
        store_shield_certificate,
        persist_managed_account,
    ):
        dialog = AddAccountDialog(_ProxyStore())
        shield_dialog = MagicMock()
        shield_dialog.exec.return_value = dialog.DialogCode.Accepted
        shield_dialog.get_code.return_value = "123456"
        shield_dialog_cls.return_value = shield_dialog
        validate_security_code.return_value = {"id": 42, "encodedCertificate": "abc"}

        def run_task(task, on_success=None, on_error=None):
            del on_error
            result = task(None)
            if on_success is not None:
                on_success(result)

        with patch.object(dialog, "_run_worker", side_effect=run_task):
            dialog._show_shield_dialog(
                {
                    "access_token": "access-token",
                    "refresh_token": "refresh-token",
                    "account_id": 7,
                },
                "demo@example.com",
                "Demo",
            )

        validate_security_code.assert_called_once_with("access-token", "123456")
        store_shield_certificate.assert_called_once_with(
            "demo@example.com",
            {"id": 42, "encodedCertificate": "abc"},
        )
        persist_managed_account.assert_called_once_with(
            "demo@example.com",
            7,
            "access-token",
            "refresh-token",
            alias="Demo",
        )

    def test_account_meta_set_meta_adds_meta(self):
        from ankama_launcher_emulator.haapi.account_meta import AccountMeta

        meta = AccountMeta()
        meta._data = {"demo@example.com": {"fake_uuid": "deadbeef", "source": "managed"}}

        with patch.object(meta, "_save") as save:
            meta.set_meta("demo@example.com", source="other")

        entry = meta._data["demo@example.com"]
        self.assertEqual(entry["fake_uuid"], "deadbeef")
        self.assertEqual(entry["source"], "other")
        self.assertIn("added_at", entry)
        save.assert_called_once()

    @patch("ankama_launcher_emulator.haapi.pkce_auth.fetch_account_profile")
    def test_complete_embedded_login_returns_launcher_account_payload(
        self,
        fetch_account_profile,
    ):
        from ankama_launcher_emulator.haapi.pkce_auth import complete_embedded_login

        session = MagicMock()
        session.exchange.return_value = {
            "access_token": "access-token",
            "refresh_token": "refresh-token",
        }
        fetch_account_profile.return_value = {
            "id": 9,
            "login": "demo@example.com",
            "nickname": "Demo",
            "security": ["SHIELD"],
        }

        data = complete_embedded_login("auth-code", session, "demo@example.com")

        # exchange is called with "auth-code"; cookies kwarg may be passed by impl
        session.exchange.assert_called_once_with("auth-code", cookies=ANY)
        fetch_account_profile.assert_called_once_with("access-token")
        self.assertEqual(
            data,
            {
                "access_token": "access-token",
                "refresh_token": "refresh-token",
                "account_id": 9,
                "login": "demo@example.com",
                "nickname": "Demo",
                "security": ["SHIELD"],
            },
        )

    @unittest.skipUnless(sys.platform == "win32", "Device.getOsVersion is Windows-only")
    @patch("ankama_launcher_emulator.gui.main_window.run_in_background")
    @patch("ankama_launcher_emulator.gui.main_window.persist_managed_account")
    @patch("ankama_launcher_emulator.gui.main_window.store_shield_certificate")
    @patch("ankama_launcher_emulator.gui.main_window.validate_security_code")
    @patch("ankama_launcher_emulator.gui.main_window.request_security_code")
    @patch("ankama_launcher_emulator.gui.main_window.complete_embedded_login")
    @patch("ankama_launcher_emulator.gui.main_window.ShieldCodeDialog")
    @patch("ankama_launcher_emulator.gui.main_window._load_embedded_auth_dialog_class")
    def test_handle_shield_recovery_reauthenticates_and_retries_launch(
        self,
        load_dialog_class,
        shield_dialog_cls,
        complete_embedded_login,
        request_security_code,
        validate_security_code,
        store_shield_certificate,
        persist_managed_account,
        run_in_background,
    ):
        server = _ServerWithHandler()
        window = MainWindow(
            server,
            [{"apikey": {"login": "demo@example.com"}}],
            {},
        )
        launch = MagicMock(return_value=1234)
        card = MagicMock()
        window._launch_contexts["demo@example.com"] = {
            "launch": launch,
            "card": card,
            "interface_ip": None,
            "proxy_url": "socks5://127.0.0.1:9050",
        }
        window._proxy_store = MagicMock()

        browser_dialog = MagicMock()
        browser_dialog.exec.return_value = QDialog.DialogCode.Accepted
        browser_dialog.get_code.return_value = "auth-code"
        load_dialog_class.return_value.return_value = browser_dialog

        shield_dialog = MagicMock()
        shield_dialog.exec.return_value = QDialog.DialogCode.Accepted
        shield_dialog.get_code.return_value = "654321"
        shield_dialog_cls.return_value = shield_dialog

        complete_embedded_login.return_value = {
            "access_token": "access-token",
            "refresh_token": "refresh-token",
            "account_id": 7,
            "login": "demo@example.com",
            "nickname": "Demo",
            "security": ["SHIELD"],
        }
        validate_security_code.return_value = {"id": 42, "encodedCertificate": "abc"}

        def run_task(task, on_success=None, on_error=None, on_progress=None, parent=None):
            del on_error, on_progress, parent
            result = task(lambda _msg: None)
            if on_success is not None:
                on_success(result)

        run_in_background.side_effect = run_task

        window._handle_shield_recovery(
            ShieldRecoveryRequired("demo@example.com"),
            launch,
            card,
        )

        complete_embedded_login.assert_called_once()
        request_security_code.assert_called_once_with("access-token")
        validate_security_code.assert_called_once_with("access-token", "654321")
        store_shield_certificate.assert_called_once_with(
            "demo@example.com",
            {"id": 42, "encodedCertificate": "abc"},
        )
        persist_managed_account.assert_called_once_with(
            "demo@example.com",
            7,
            "access-token",
            "refresh-token",
            alias="Demo",
        )
        window._proxy_store.save_validated.assert_called_once_with(
            "demo@example.com",
            "socks5://127.0.0.1:9050",
        )
        launch.assert_called_once()

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

    @unittest.skipUnless(sys.platform == "win32", "Device.getUUID is Windows-only")
    @patch("ankama_launcher_emulator.server.handler.AccountMeta")
    @patch("ankama_launcher_emulator.server.handler.CryptoHelper.getStoredCertificate")
    @patch("ankama_launcher_emulator.server.handler.CryptoHelper.createHmEncoders")
    def test_auth_get_game_token_notifies_shield_recovery_callback(
        self,
        create_hm_encoders,
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
        create_hm_encoders.return_value = ("hm1", "hm2")
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

    @_patch_credentials
    @patch("ankama_launcher_emulator.gui.main_window.run_in_background")
    @patch.object(MainWindow, "_handle_shield_light")
    def test_proxy_change_detected_before_launch_triggers_shield_light(
        self,
        handle_shield_light,
        run_in_background,
        _creds,
    ):
        """P2: pre-launch cert proxy change check routes to shield light, skips run_in_background."""
        window = MainWindow(
            _DummyServer(),
            [{"apikey": {"login": "demo@example.com"}}],
            {},
        )
        card = window._find_card("demo@example.com")
        proxy_store = MagicMock()
        proxy_store.get_proxy_url.return_value = "socks5://new-proxy:9050"
        window._proxy_store = proxy_store

        with patch("ankama_launcher_emulator.gui.main_window.AccountMeta") as mock_meta:
            mock_meta.return_value.cert_proxy_changed.return_value = True
            mock_meta.return_value.get.return_value = {"portable_mode": False}
            handler = window._make_launch_handler("demo@example.com", card)
            handler(None, "some-proxy-id")

        handle_shield_light.assert_called_once()
        run_in_background.assert_not_called()

    # --- P1: remove_account subdir cleanup ---

    @patch("ankama_launcher_emulator.haapi.account_manager.os.rmdir")
    @patch("ankama_launcher_emulator.haapi.account_manager.os.unlink")
    @patch("ankama_launcher_emulator.haapi.account_manager.AccountMeta")
    @patch("ankama_launcher_emulator.haapi.account_manager.CryptoHelper.createHashFromStringSha", return_value="abc123")
    @patch("ankama_launcher_emulator.haapi.account_manager.Device.getUUID", return_value="dev-uuid")
    @patch("ankama_launcher_emulator.haapi.account_manager.CryptoHelper.getStoredApiKey")
    def test_remove_account_calls_rmdir_on_per_account_subdirs(
        self,
        mock_get_key,
        _get_uuid,
        _hash,
        mock_meta,
        mock_unlink,
        mock_rmdir,
    ):
        from ankama_launcher_emulator.haapi.account_manager import remove_account

        mock_get_key.return_value = {"apikeyFile": ".keyabc123", "apikey": {}}
        mock_meta.return_value.get.return_value = {"fake_uuid": "fake-uuid"}

        remove_account("demo@example.com", api_key=None)

        self.assertGreater(mock_rmdir.call_count, 0, "os.rmdir should be called to clean up per-account subdirs")
        rmdir_paths = [c.args[0] for c in mock_rmdir.call_args_list]
        self.assertTrue(
            any("abc123" in p for p in rmdir_paths),
            f"Expected per-account sha subdir in rmdir calls, got: {rmdir_paths}",
        )

    def test_remove_account_subdir_cleanup_leaves_no_empty_dirs(self):
        """Integration: actual filesystem dirs are removed after remove_account."""
        from ankama_launcher_emulator.haapi.account_manager import remove_account

        with tempfile.TemporaryDirectory() as tmpdir:
            cert_hash = "deadbeef12345678"
            key_dir = os.path.join(tmpdir, "keydata", cert_hash)
            cert_dir = os.path.join(tmpdir, "cert", cert_hash)
            os.makedirs(key_dir)
            os.makedirs(cert_dir)
            key_file = os.path.join(key_dir, f".key{cert_hash}")
            cert_file = os.path.join(cert_dir, f".certif{cert_hash}")
            open(key_file, "w").close()
            open(cert_file, "w").close()

            from ankama_launcher_emulator.consts import (
                ALT_API_KEY_FOLDER_PATH,
                ALT_CERTIFICATE_FOLDER_PATH,
            )

            mock_stored = {"apikeyFile": f".key{cert_hash}", "apikey": {}}

            with patch("ankama_launcher_emulator.haapi.account_manager.CryptoHelper.getStoredApiKey", return_value=mock_stored), \
                 patch("ankama_launcher_emulator.haapi.account_manager.CryptoHelper.createHashFromStringSha", return_value=cert_hash), \
                 patch("ankama_launcher_emulator.haapi.account_manager.Device.getUUID", return_value="uuid"), \
                 patch("ankama_launcher_emulator.haapi.account_manager.AccountMeta") as mock_meta, \
                 patch("ankama_launcher_emulator.haapi.account_manager.ALT_API_KEY_FOLDER_PATH", os.path.join(tmpdir, "keydata")), \
                 patch("ankama_launcher_emulator.haapi.account_manager.ALT_CERTIFICATE_FOLDER_PATH", os.path.join(tmpdir, "cert")):
                mock_meta.return_value.get.return_value = {"fake_uuid": "fake-uuid"}
                remove_account("demo@example.com", api_key=None)

            self.assertFalse(os.path.exists(key_dir), "key subdir should be deleted")
            self.assertFalse(os.path.exists(cert_dir), "cert subdir should be deleted")

    # --- P2: cert validation tracking ---

    def test_account_meta_cert_proxy_changed_returns_false_when_no_record(self):
        from ankama_launcher_emulator.haapi.account_meta import AccountMeta

        meta = AccountMeta()
        meta._data = {}
        self.assertFalse(meta.cert_proxy_changed("demo@example.com", "socks5://1.2.3.4:9050"))

    def test_account_meta_cert_proxy_changed_detects_proxy_switch(self):
        from ankama_launcher_emulator.haapi.account_meta import AccountMeta

        meta = AccountMeta()
        meta._data = {"demo@example.com": {"cert_validated_proxy_url": "socks5://old:9050"}}
        self.assertTrue(meta.cert_proxy_changed("demo@example.com", "socks5://new:9050"))
        self.assertFalse(meta.cert_proxy_changed("demo@example.com", "socks5://old:9050"))

    def test_account_meta_cert_proxy_changed_detects_proxy_removal(self):
        from ankama_launcher_emulator.haapi.account_meta import AccountMeta

        meta = AccountMeta()
        meta._data = {"demo@example.com": {"cert_validated_proxy_url": "socks5://old:9050"}}
        self.assertTrue(meta.cert_proxy_changed("demo@example.com", None))

    def test_account_meta_record_cert_validated_persists_proxy_url(self):
        from ankama_launcher_emulator.haapi.account_meta import AccountMeta

        meta = AccountMeta()
        meta._data = {"demo@example.com": {}}
        with patch.object(meta, "_save") as mock_save:
            meta.record_cert_validated("demo@example.com", "socks5://1.2.3.4:9050")

        self.assertEqual(
            meta._data["demo@example.com"]["cert_validated_proxy_url"],
            "socks5://1.2.3.4:9050",
        )
        mock_save.assert_called_once()

    # --- P3: 500 error fallback ---

    def test_create_token_500_with_certificate_raises_shield_recovery_required(self):
        """P3: 500 from Ankama when cert is sent → treated as stale cert."""
        haapi = Haapi("apikey", "demo@example.com", None, None)
        haapi.zaap_session = MagicMock()
        response = MagicMock()
        response.status_code = 500
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

    def test_create_token_500_without_certificate_propagates_http_error(self):
        """P3: 500 without cert (no cert sent) still raises HTTPError."""
        haapi = Haapi("apikey", "demo@example.com", None, None)
        haapi.zaap_session = MagicMock()
        response = MagicMock()
        response.status_code = 500
        response.raise_for_status.side_effect = requests.exceptions.HTTPError("500 Server Error")
        haapi.zaap_session.get.return_value = response

        with self.assertRaises(requests.exceptions.HTTPError):
            haapi.createToken(102, None)

    @patch("ankama_launcher_emulator.server.handler.os.unlink")
    @patch("ankama_launcher_emulator.server.handler.CryptoHelper.createHashFromStringSha", return_value="abc123")
    @patch("ankama_launcher_emulator.server.handler.CryptoHelper.getStoredCertificate")
    @patch("ankama_launcher_emulator.server.handler.CryptoHelper.get_crypto_context")
    def test_auth_get_game_token_deletes_stale_cert_on_shield_recovery(
        self,
        get_crypto_context,
        get_stored_certificate,
        _hash,
        mock_unlink,
    ):
        """P3: when ShieldRecoveryRequired is raised, stale cert file is deleted."""
        get_crypto_context.return_value = ("uuid", "/certdir", "/keydir", "hm1", "hm2")
        get_stored_certificate.side_effect = FileNotFoundError

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
        handler.on_shield_recovery = MagicMock()

        with self.assertRaises(ShieldRecoveryRequired):
            handler.auth_getGameToken("hash", 102)

        mock_unlink.assert_called_once()
        deleted_path = mock_unlink.call_args.args[0]
        self.assertIn(".certif", deleted_path)
        self.assertIn("abc123", deleted_path)

    # --- P4: proxy blacklist detection ---

    @_patch_credentials
    @patch("ankama_launcher_emulator.gui.main_window.run_in_background")
    def test_shield_light_proceeds_directly_to_email_code_request(self, run_in_background, _creds):
        """P4: shield light flow requests email code without any proactive proxy test.

        A new proxy that legitimately needs shield cert returns the same 403 as a
        blocked proxy on SignOnWithApiKey — no reliable distinction exists at that
        layer. Proxy-blocked detection is left to Tier-2 resend counter only.
        """
        window = MainWindow(
            _DummyServer(),
            [{"apikey": {"login": "demo@example.com"}}],
            {},
        )
        card = window._find_card("demo@example.com")
        assert card is not None
        window._launch_contexts["demo@example.com"] = {
            "proxy_url": "socks5://new-proxy:9050",
            "interface_ip": None,
        }

        tasks_dispatched = []

        def capture_task(task, **_kwargs):
            tasks_dispatched.append(task)

        run_in_background.side_effect = capture_task
        window._handle_shield_light("demo@example.com", MagicMock(), card)

        self.assertEqual(len(tasks_dispatched), 1, "Expected exactly one background task (request_code)")
        # Verify no check_proxy_needs_shield import left in scope
        import ankama_launcher_emulator.gui.main_window as mw_module
        self.assertFalse(
            hasattr(mw_module, "check_proxy_needs_shield"),
            "check_proxy_needs_shield must not be importable from main_window",
        )

    def test_shield_code_dialog_resend_button_shows_warning_after_max_attempts(self):
        """P4: resend counter in ShieldCodeDialog shows warning after 3 resends."""
        from ankama_launcher_emulator.gui.shield_dialog import ShieldCodeDialog

        dialog = ShieldCodeDialog("demo@example.com")
        resend_signal_count = []
        dialog.resend_requested.connect(lambda: resend_signal_count.append(1))

        # Initially hidden — isVisibleTo checks parent-agnostic explicit visibility
        self.assertFalse(dialog._proxy_warning.isVisibleTo(dialog))

        dialog._on_resend()
        self.assertEqual(len(resend_signal_count), 1)
        self.assertFalse(dialog._proxy_warning.isVisibleTo(dialog))

        dialog._resend_btn.setEnabled(True)
        dialog._on_resend()
        self.assertFalse(dialog._proxy_warning.isVisibleTo(dialog))

        dialog._resend_btn.setEnabled(True)
        dialog._on_resend()
        self.assertTrue(
            dialog._proxy_warning.isVisibleTo(dialog),
            "Warning should appear after 3 resends",
        )

    def test_shield_code_dialog_resend_done_false_shows_warning_immediately(self):
        """P4: resend_done(success=False) shows warning before max attempts."""
        from ankama_launcher_emulator.gui.shield_dialog import ShieldCodeDialog

        dialog = ShieldCodeDialog("demo@example.com")
        self.assertFalse(dialog._proxy_warning.isVisibleTo(dialog))

        dialog.resend_done(success=False)

        self.assertTrue(dialog._proxy_warning.isVisibleTo(dialog))
        self.assertTrue(dialog._resend_btn.isEnabled())

    # --- P5: official account protection ---

    def test_list_all_api_keys_tags_official_folder_accounts(self):
        """P5: accounts from official Zaap folder scan get is_official=True."""
        from ankama_launcher_emulator.haapi.account_persistence import list_all_api_keys

        managed_acc = {
            "apikeyFile": ".keymanaged",
            "apikey": {"login": "managed@test.com", "key": "k", "provider": "ankama",
                       "refreshToken": "", "isStayLoggedIn": True, "accountId": 1,
                       "certificate": {}, "refreshDate": 0},
        }
        official_acc = {
            "apikeyFile": ".keyofficial",
            "apikey": {"login": "official@test.com", "key": "k", "provider": "ankama",
                       "refreshToken": "", "isStayLoggedIn": True, "accountId": 2,
                       "certificate": {}, "refreshDate": 0},
        }

        with patch("ankama_launcher_emulator.haapi.account_persistence.AccountMeta") as mock_meta, \
             patch("ankama_launcher_emulator.haapi.account_persistence.CryptoHelper.get_crypto_context") as ctx, \
             patch("ankama_launcher_emulator.haapi.account_persistence.CryptoHelper.getStoredApiKey", return_value=managed_acc), \
             patch("ankama_launcher_emulator.haapi.account_persistence.CryptoHelper.getStoredApiKeys", return_value=[official_acc]), \
             patch("ankama_launcher_emulator.decrypter.device.Device.getUUID", return_value="uuid"):

            mock_meta.return_value.all_entries.return_value = {"managed@test.com": {"fake_uuid": "uuid"}}
            mock_meta.return_value.repair_corrupt_entries.return_value = 0
            ctx.return_value = ("uuid", "/cert", "/key", "hm1", "hm2")

            results = list_all_api_keys()

        managed = next((r for r in results if r["apikey"]["login"] == "managed@test.com"), None)
        official = next((r for r in results if r["apikey"]["login"] == "official@test.com"), None)

        self.assertIsNotNone(managed)
        self.assertIsNotNone(official)
        self.assertFalse(managed.get("is_official", False), "managed account must NOT be is_official")
        self.assertTrue(official.get("is_official", False), "official Zaap account must be is_official")

    @_patch_credentials
    def test_official_account_card_hides_remove_button(self, _creds):
        """P5: AccountCard with is_official=True hides the X remove button."""
        from ankama_launcher_emulator.gui.account_card import AccountCard

        card = AccountCard("official@test.com", {}, _ProxyStore(), is_official=True)
        self.assertFalse(card._remove_btn.isVisible())

    @_patch_credentials
    def test_managed_account_card_shows_remove_button(self, _creds):
        """P5: AccountCard with is_official=False (default) shows the X remove button."""
        from ankama_launcher_emulator.gui.account_card import AccountCard

        card = AccountCard("managed@test.com", {}, _ProxyStore(), is_official=False)
        # isVisibleTo checks "would be visible if parent were shown" — parent-agnostic
        self.assertTrue(card._remove_btn.isVisibleTo(card))

    @_patch_credentials
    def test_remove_account_blocked_for_official_accounts(self, _creds):
        """P5: _on_remove_account rejects deletion when no AccountMeta entry (official)."""
        window = MainWindow(
            _DummyServer(),
            [{"apikey": {"login": "demo@example.com"}}],
            {},
        )
        card = window._find_card("demo@example.com")

        with patch("ankama_launcher_emulator.gui.main_window.AccountMeta") as mock_meta, \
             patch.object(window, "_show_error") as mock_error:
            mock_meta.return_value.get.return_value = None  # no meta = official account
            window._on_remove_account("demo@example.com", card)

        mock_error.assert_called_once()
        self.assertIn("official", mock_error.call_args.args[0].lower())
