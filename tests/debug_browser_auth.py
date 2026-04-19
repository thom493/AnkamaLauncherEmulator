"""Interactive debug harness for AddAccountDialog's browser-PKCE → Shield flow.

Purpose
-------
Hunt the "CaptionLabel has been deleted" crash that surfaces at
`AddAccountDialog._handle_shield` after the embedded browser returns tokens.

What this harness does
----------------------
1. Runs the real `AddAccountDialog` with every method, every worker, and
   every child widget wired into a verbose tracer.
2. Hooks `destroyed` on the dialog + each widget that the flow touches
   (status label, portable switch, indicator, buttons). The first widget
   to die prints a stack trace — that tells us WHO killed it.
3. Streams HTTP via the shared `_debug_session` hook so the PKCE + Shield
   calls are visible inline.
4. Offers knobs to skip the expensive real-world steps:
     --mock-browser   bypass Chromium, inject synthetic tokens
     --mock-profile   inject account_profile (SHIELD on by default)
     --mock-shield    auto-provide a Shield code, auto-accept dialog
     --no-persist     skip final `persist_managed_account`

Usage
-----
    # real browser, real profile fetch, real shield email — Windows repro
    python tests/debug_browser_auth.py

    # skip browser: inject tokens, still real /Account call
    python tests/debug_browser_auth.py --mock-browser

    # skip everything external, trigger _handle_shield directly
    python tests/debug_browser_auth.py --mock-browser --mock-profile

    # full synthetic: harness reaches _persist_account with no I/O
    python tests/debug_browser_auth.py --mock-browser --mock-profile --mock-shield

Credentials come from tests/.env (ANKAMA_TEST_LOGIN / ANKAMA_TEST_PASSWORD)
or the prompt fallback — same as debug_login.py.
"""

from __future__ import annotations

import argparse
import os
import sys
import traceback
import urllib3
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

from tests import _debug_session as dbg


# ──────────────────────────────────────────────────────────────────────────────
# Widget lifecycle tracer
# ──────────────────────────────────────────────────────────────────────────────


def _sip_id(obj) -> str:
    """Short sip-wrapper id for a QObject — stable across the widget's life."""
    if obj is None:
        return "<None>"
    try:
        return f"{type(obj).__name__}@{id(obj):x}"
    except Exception:
        return "<unprintable>"


def _is_alive(obj) -> bool:
    """True if the underlying C++ object still exists."""
    if obj is None:
        return False
    try:
        from PyQt6 import sip
    except ImportError:  # pragma: no cover — PyQt6 always ships sip
        return True
    try:
        return not sip.isdeleted(obj)
    except TypeError:
        return True


def _describe(obj) -> str:
    tag = _sip_id(obj)
    return f"{tag}{'' if _is_alive(obj) else ' [DELETED]'}"


class WidgetTracer:
    """Attaches destroyed hooks to every widget we care about.

    `watch(widget, label)` subscribes to the widget's `destroyed` signal
    and records a stack trace. Whoever kills it first shows up in the log.
    """

    def __init__(self) -> None:
        self._seen: set[int] = set()

    def watch(self, widget, label: str) -> None:
        if widget is None:
            return
        key = id(widget)
        if key in self._seen:
            return
        self._seen.add(key)
        tag = _sip_id(widget)
        dbg.info(f"[watch] {label}: {tag}")
        try:
            widget.destroyed.connect(lambda *_: self._on_destroyed(label, tag))
        except Exception as exc:
            dbg.info(f"[watch] failed to attach destroyed for {label}: {exc}")

    def _on_destroyed(self, label: str, tag: str) -> None:
        print()
        print(f"  {dbg._RED}[destroyed] {label} ({tag}){dbg._END}")
        # Short stack — we only care about the top frames inside the app code
        tb_lines = traceback.format_stack(limit=14)
        interesting = [
            line for line in tb_lines
            if "ankama_launcher_emulator" in line
            or "debug_browser_auth" in line
            or "PyQt6" in line
            or "qfluentwidgets" in line
        ]
        for line in interesting[-8:]:
            print(f"  {dbg._DIM}{line.strip()}{dbg._END}")


# ──────────────────────────────────────────────────────────────────────────────
# Dialog instrumentation
# ──────────────────────────────────────────────────────────────────────────────


def _instrument_add_account_dialog(tracer: WidgetTracer) -> None:
    """Wrap every interesting AddAccountDialog method with an entry/exit tracer.

    Every wrapped call logs:
      • `self` sip id + aliveness
      • the widgets the method is about to touch (status_label, portable_switch)
      • an "entered" + "returned" pair so reentrancy shows up clearly
    """
    from ankama_launcher_emulator.gui import add_account_dialog as mod

    cls = mod.AddAccountDialog
    targets = [
        "_on_add",
        "_start_browser_login",
        "_on_login_success",
        "_handle_shield",
        "_show_shield_dialog",
        "_persist_account",
        "_run_worker",
        "_on_worker_done",
        "_finalise_done",
        "done",
        "closeEvent",
        "accept",
        "reject",
        "hide",
    ]

    for name in targets:
        original = getattr(cls, name, None)
        if original is None:
            continue
        wrapped = _wrap_method(name, original, tracer)
        setattr(cls, name, wrapped)

    # After the dialog is built, watch its widget tree.
    original_setup = cls._setup_ui

    def wrapped_setup_ui(self):
        dbg.info(f"[AddAccountDialog] _setup_ui start on {_sip_id(self)}")
        original_setup(self)
        tracer.watch(self, "AddAccountDialog")
        tracer.watch(self._status_label, "status_label (CaptionLabel)")
        tracer.watch(self._portable_switch, "portable_switch (SwitchButton)")
        tracer.watch(self._add_btn, "add_btn (PrimaryPushButton)")
        indicator = getattr(self._portable_switch, "indicator", None)
        tracer.watch(indicator, "portable_switch.indicator")
        tracer.watch(self._login_input, "login_input")
        tracer.watch(self._password_input, "password_input")
        dbg.info(f"[AddAccountDialog] _setup_ui done on {_sip_id(self)}")

    cls._setup_ui = wrapped_setup_ui


def _wrap_method(name: str, original, tracer: WidgetTracer):
    def wrapper(self, *args, **kwargs):
        dbg.info(
            f"[call]  AddAccountDialog.{name}  self={_describe(self)}  "
            f"inflight={getattr(self, '_inflight', '?')}  "
            f"cancelled={getattr(self, '_cancelled', '?')}  "
            f"pending_done={getattr(self, '_pending_done', '?')}"
        )
        # Check the three widgets we're about to touch on this call
        for attr in ("_status_label", "_portable_switch", "_add_btn"):
            w = getattr(self, attr, None)
            if w is not None:
                marker = "" if _is_alive(w) else f"  {dbg._RED}!! DEAD !!{dbg._END}"
                print(f"    {dbg._DIM}- {attr}: {_describe(w)}{dbg._END}{marker}")
        try:
            rv = original(self, *args, **kwargs)
        except Exception:
            dbg.fail(f"[call]  AddAccountDialog.{name} RAISED")
            traceback.print_exc()
            raise
        dbg.info(f"[ret]   AddAccountDialog.{name}  self={_describe(self)}")
        return rv

    wrapper.__name__ = name
    wrapper.__qualname__ = f"AddAccountDialog.{name}"
    return wrapper


def _instrument_worker_signals() -> None:
    """Log every `_run_worker` callback, so we see the exact success→UI hop.

    The CaptionLabel crash happens inside the worker-success callback, so
    knowing the exact moment of emit is the whole point.
    """
    from ankama_launcher_emulator.gui import utils as utils_mod

    original_run = utils_mod.Worker.run

    def patched_run(self):
        dbg.info(f"[worker] Worker.run start  worker={_sip_id(self)}")
        try:
            original_run(self)
        finally:
            dbg.info(f"[worker] Worker.run end    worker={_sip_id(self)}")

    utils_mod.Worker.run = patched_run


# ──────────────────────────────────────────────────────────────────────────────
# Mock stubs
# ──────────────────────────────────────────────────────────────────────────────


def _install_mock_browser(login: str, tokens: dict) -> None:
    """Replace the embedded browser dialog with a synchronous stub.

    The stub mimics the surface used by `_start_browser_login`:
    `dialog.exec()`, `dialog.get_tokens()`, `dialog.get_token_error()`,
    `dialog.deleteLater()`. It also keeps a tiny QDialog around so the sip
    lifetimes are realistic (deleteLater actually runs).
    """
    from PyQt6.QtWidgets import QDialog
    from ankama_launcher_emulator.gui import add_account_dialog as mod

    class _MockBrowserDialog(QDialog):
        def __init__(self, *_args, **_kwargs):
            super().__init__()

        def exec(self) -> int:
            dbg.info("[mock-browser] exec() — returning Accepted")
            return QDialog.DialogCode.Accepted

        def get_tokens(self) -> dict:
            return tokens

        def get_token_error(self):
            return None

        def get_cookies(self) -> dict:
            return {}

    def loader():
        dbg.info("[mock-browser] _load_embedded_auth_dialog_class called")
        return _MockBrowserDialog

    mod._load_embedded_auth_dialog_class = loader


def _install_mock_profile(login: str, profile: dict) -> None:
    from ankama_launcher_emulator.gui import add_account_dialog as mod

    def fake_fetch(access_token):
        dbg.info(f"[mock-profile] returning profile for {login}")
        return profile

    mod.fetch_account_profile = fake_fetch


def _install_mock_shield(code: str) -> None:
    """Auto-fill and auto-accept ShieldCodeDialog + stub the HTTP calls."""
    from PyQt6.QtCore import QTimer
    from PyQt6.QtWidgets import QDialog
    from ankama_launcher_emulator.gui import add_account_dialog as mod
    from ankama_launcher_emulator.gui import shield_dialog as shield_mod

    original_ctor = shield_mod.ShieldCodeDialog.__init__

    def patched_ctor(self, *args, **kwargs):
        original_ctor(self, *args, **kwargs)
        dbg.info(f"[mock-shield] ShieldCodeDialog built: {_sip_id(self)}")
        # Accept on next tick so the modal exec() returns immediately
        def _auto():
            dbg.info(f"[mock-shield] auto-filling code and accepting")
            self._code_input.setText(code)
            self._on_submit()
        QTimer.singleShot(50, _auto)

    shield_mod.ShieldCodeDialog.__init__ = patched_ctor

    # Stub HTTP sides
    def fake_request_security_code(access_token, **kwargs):
        dbg.info("[mock-shield] request_security_code stubbed (no email sent)")
        return {"ok": True}

    def fake_validate_security_code(access_token, code, **kwargs):
        dbg.info(f"[mock-shield] validate_security_code(code={code!r}) stubbed")
        return {"id": 999, "encodedCertificate": "FAKE"}

    def fake_store_certificate(*args, **kwargs):
        dbg.info("[mock-shield] store_shield_certificate stubbed (no disk write)")

    mod.request_security_code = fake_request_security_code
    mod.validate_security_code = fake_validate_security_code
    mod.store_shield_certificate = fake_store_certificate


def _install_mock_headless() -> None:
    """Make programmatic_pkce_login fail instantly so the browser path fires.

    The dialog's fallback predicate already matches "Failed to extract CSRF
    state" (see _should_use_browser_login), so this gives an immediate and
    realistic route into _start_browser_login without any HTTP.
    """
    from ankama_launcher_emulator.gui import add_account_dialog as mod

    def fake_pkce(login, password, proxy_url=None, on_progress=None):
        dbg.info(f"[mock-headless] programmatic_pkce_login faked → CSRF failure")
        if on_progress is not None:
            on_progress("Mock headless attempt…")
        raise RuntimeError("Failed to extract CSRF state from login page")

    mod.programmatic_pkce_login = fake_pkce


def _install_no_persist() -> None:
    from ankama_launcher_emulator.gui import add_account_dialog as mod

    def fake_persist(*args, **kwargs):
        dbg.info("[no-persist] persist_managed_account stubbed (no disk write)")

    mod.persist_managed_account = fake_persist


# ──────────────────────────────────────────────────────────────────────────────
# Flow driver
# ──────────────────────────────────────────────────────────────────────────────


def _prompt_creds(args: argparse.Namespace) -> tuple[str, str]:
    dbg.load_dotenv()
    login = args.login or os.environ.get("ANKAMA_TEST_LOGIN")
    password = args.password or os.environ.get("ANKAMA_TEST_PASSWORD") or ""
    if not login:
        login = input("Login (email): ").strip()
    # Password only required when not fully mocked
    return login, password


def _fake_profile(login: str, with_shield: bool) -> dict:
    security = ["SHIELD"] if with_shield else []
    return {
        "id": 424242,
        "login": login,
        "nickname": login.split("@")[0],
        "security": security,
    }


def _fake_tokens() -> dict:
    return {
        "access_token": "fake-access-" + "a" * 24,
        "refresh_token": "fake-refresh-" + "b" * 24,
    }


def _run(args: argparse.Namespace) -> int:
    if args.offscreen:
        os.environ["QT_QPA_PLATFORM"] = "offscreen"

    from PyQt6.QtCore import Qt, QCoreApplication, QTimer
    QCoreApplication.setAttribute(Qt.ApplicationAttribute.AA_ShareOpenGLContexts, True)
    from ankama_launcher_emulator.gui.app import ensure_app
    app = ensure_app()

    login, password = _prompt_creds(args)

    dbg.install_global_hook()
    tracer = WidgetTracer()

    # ── Install all mocks BEFORE building the dialog ──────────────────────────
    if args.mock_headless:
        _install_mock_headless()
    if args.mock_browser:
        _install_mock_browser(login, _fake_tokens())
    if args.mock_profile:
        _install_mock_profile(login, _fake_profile(login, with_shield=not args.no_shield))
    if args.mock_shield:
        code = args.shield_code or os.environ.get("ANKAMA_TEST_SHIELD_CODE", "123456")
        _install_mock_shield(code)
    if args.no_persist:
        _install_no_persist()

    _instrument_add_account_dialog(tracer)
    _instrument_worker_signals()

    from ankama_launcher_emulator.gui.add_account_dialog import AddAccountDialog

    class _NullProxyStore:
        def list_proxies(self):
            return {}

        def get_proxy(self, _pid):
            return None

    dbg.banner(f"ADD-ACCOUNT BROWSER FLOW — {login}")
    dialog = AddAccountDialog(_NullProxyStore())
    tracer.watch(dialog, "AddAccountDialog(top)")

    # Pre-fill inputs and click Add
    dialog._login_input.setText(login)
    dialog._password_input.setText(password or "mock-password-if-browser-skipped")

    # Kick off the flow after exec() starts so the modal loop is running
    def _kick():
        dbg.banner("CLICKING ADD")
        # The headless path will fail + fall back to browser (real or mock).
        # If `--force-browser`, we patch the fallback predicate to always fire.
        if args.force_browser:
            from ankama_launcher_emulator.gui import add_account_dialog as mod
            mod._should_use_browser_login = lambda _err: True
            dbg.info("[setup] forcing browser fallback for every error")
        dialog._on_add()

    QTimer.singleShot(100, _kick)

    from PyQt6.QtWidgets import QDialog
    rc = dialog.exec()
    dbg.banner(f"DIALOG EXEC RETURNED {rc}")
    status = dialog._status_label.text() if _is_alive(dialog._status_label) else "<dead>"
    dbg.info(f"final dialog status: {status}")
    dialog.deleteLater()
    app.processEvents()
    return 0 if rc == QDialog.DialogCode.Accepted else 1


# ──────────────────────────────────────────────────────────────────────────────
# Entry
# ──────────────────────────────────────────────────────────────────────────────


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--login", help="Override ANKAMA_TEST_LOGIN")
    parser.add_argument("--password", help="Override ANKAMA_TEST_PASSWORD")
    parser.add_argument("--shield-code", help="Override mock Shield code (default 123456)")

    parser.add_argument(
        "--mock-headless", action="store_true",
        help="Short-circuit programmatic_pkce_login with an instant CSRF error",
    )
    parser.add_argument(
        "--mock-browser", action="store_true",
        help="Bypass Chromium, return synthetic tokens from _start_browser_login",
    )
    parser.add_argument(
        "--mock-profile", action="store_true",
        help="Stub fetch_account_profile so no real /Account call is made",
    )
    parser.add_argument(
        "--mock-shield", action="store_true",
        help="Auto-fill + auto-accept ShieldCodeDialog and stub request/validate",
    )
    parser.add_argument(
        "--no-shield", action="store_true",
        help="When --mock-profile, return a profile with no SHIELD security",
    )
    parser.add_argument(
        "--no-persist", action="store_true",
        help="Stub persist_managed_account so the harness makes no disk writes",
    )
    parser.add_argument(
        "--force-browser", action="store_true",
        help="Patch fallback predicate so any headless error → browser path",
    )
    parser.add_argument(
        "--offscreen", action="store_true",
        help="Use QT_QPA_PLATFORM=offscreen (no window, useful for CI)",
    )
    args = parser.parse_args()

    return _run(args)


if __name__ == "__main__":
    sys.exit(main())
