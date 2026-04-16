"""Compatibility shim for older imports of the embedded auth browser dialog."""

from ankama_launcher_emulator.gui.embedded_auth_browser_dialog import (
    EmbeddedAuthBrowserDialog as ShieldBrowserDialog,
)

__all__ = ["ShieldBrowserDialog"]
