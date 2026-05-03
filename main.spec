# -*- mode: python ; coding: utf-8 -*-

import os
import subprocess
import tempfile

from PyInstaller.utils.hooks import collect_all


def _get_build_version() -> str:
    """Resolve a version string at build time: package metadata > git tag > fallback."""
    # Prefer installed package metadata so the PE version matches the runtime
    # version reported inside a PyInstaller bundle.
    try:
        from importlib.metadata import version

        return version("ankama_launcher_emulator")
    except Exception:
        pass
    spec_dir = os.path.dirname(os.path.abspath(__SPEC__))
    try:
        result = subprocess.run(
            ["git", "describe", "--tags", "--always", "--dirty"],
            cwd=spec_dir,
            capture_output=True,
            text=True,
            check=True,
        )
        raw = result.stdout.strip()
        if raw:
            return raw.lstrip("vV")
    except Exception:
        pass
    return "0.0.0"


def _to_win_version_tuple(v: str) -> tuple[int, int, int, int]:
    """Parse a semver-ish string into a 4-int Windows file-version tuple."""
    nums: list[int] = []
    for part in v.split("."):
        num_str = ""
        for ch in part:
            if ch.isdigit():
                num_str += ch
            else:
                break
        if num_str:
            nums.append(int(num_str))
        if len(nums) == 4:
            break
    while len(nums) < 4:
        nums.append(0)
    return tuple(nums[:4])  # type: ignore[return-value]


_build_version = _get_build_version()
_win_vers = _to_win_version_tuple(_build_version)

_version_file = os.path.join(tempfile.gettempdir(), "ankalt_file_version_info.txt")
with open(_version_file, "w", encoding="utf-8") as _vf:
    _vf.write(
        f"""VSVersionInfo(
  ffi=FixedFileInfo(
    filevers={_win_vers},
    prodvers={_win_vers},
    mask=0x3f,
    flags=0x0,
    OS=0x40004,
    fileType=0x1,
    subtype=0x0,
    date=(0, 0)
  ),
  kids=[
    StringFileInfo(
      [
      StringTable(
        u'040904B0',
        [StringStruct(u'CompanyName', u'Valentin Alix'),
         StringStruct(u'FileDescription', u'AnkAlt Launcher'),
         StringStruct(u'FileVersion', u'{_build_version}'),
         StringStruct(u'InternalName', u'AnkAlt Launcher'),
         StringStruct(u'LegalCopyright', u''),
         StringStruct(u'OriginalFilename', u'AnkAlt Launcher.exe'),
         StringStruct(u'ProductName', u'AnkAlt Launcher'),
         StringStruct(u'ProductVersion', u'{_build_version}')])
      ]),
    VarFileInfo([VarStruct(u'Translation', [1033, 1200])])
  ]
)
"""
    )

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
    version=_version_file,
)
