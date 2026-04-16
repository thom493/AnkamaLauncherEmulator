# -*- mode: python ; coding: utf-8 -*-


a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=[],
    datas=[
        ('ankama_launcher_emulator/server/dofus3/script.js', 'ankama_launcher_emulator/server/dofus3'),
        ('ankama_launcher_emulator/server/retro/script.js', 'ankama_launcher_emulator/server/retro'),
        ('resources/Dofus3.png', 'resources'),
        ('resources/DofusRetro.png', 'resources'),
        ('resources/app.ico', 'resources'),
    ],
    hiddenimports=[
        'PyQt6.QtWebEngineCore',
        'PyQt6.QtWebEngineWidgets',
    ],
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
