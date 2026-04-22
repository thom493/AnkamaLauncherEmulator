# -*- mode: python ; coding: utf-8 -*-

from PyInstaller.utils.hooks import collect_all

# rnet ships a Rust-compiled native extension (.pyd/.so) plus submodules
# that PyInstaller's static analysis can miss. collect_all pulls the
# native binary, submodules, and any data files in one go.
_rnet_datas, _rnet_binaries, _rnet_hiddenimports = collect_all('rnet')


a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=_rnet_binaries,
    datas=[
        ('ankama_launcher_emulator/server/dofus3/script.js', 'ankama_launcher_emulator/server/dofus3'),
        ('ankama_launcher_emulator/server/retro/script.js', 'ankama_launcher_emulator/server/retro'),
        ('ankama_launcher_emulator/haapi/webgl.json', 'ankama_launcher_emulator/haapi'),
        ('resources/Dofus3.png', 'resources'),
        ('resources/DofusRetro.png', 'resources'),
        ('resources/app.ico', 'resources'),
        ('resources/load.gif', 'resources'),
    ] + _rnet_datas,
    hiddenimports=[
        'ankama_launcher_emulator.gui.embedded_auth_browser_dialog',
        'ankama_launcher_emulator.gui.shield_browser_dialog',
        'PyQt6.QtWebEngineCore',
        'PyQt6.QtWebEngineWidgets',
    ] + _rnet_hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='AnkAlt Launcher',
    icon='resources/app.ico',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
