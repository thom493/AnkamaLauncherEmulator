import json
import logging
import os
import re
import shutil
import sys
from pathlib import Path

logger = logging.getLogger()

if os.name == "nt":
    ZAAP_PATH = os.path.join(os.environ["APPDATA"], "zaap")
else:
    config_home = os.environ.get("XDG_CONFIG_HOME", os.path.expanduser("~/.config"))
    ZAAP_PATH = os.path.join(config_home, "zaap")

RELEASE_JSON_PATH = os.path.join(
    ZAAP_PATH, "repositories", "production", "dofus", "dofus3", "release.json"
)
if os.path.exists(RELEASE_JSON_PATH):
    with open(RELEASE_JSON_PATH, "r") as file:
        content = json.load(file)
        if not content.get("location"):
            DOFUS_PATH = "DUMMY_PATH"
        else:
            DOFUS_PATH = os.path.join(
                content["location"], "Dofus.exe" if os.name == "nt" else "Dofus"
            )
else:
    DOFUS_PATH = "DUMMY_PATH"
    logger.warning("<!> No Dofus path found !")
DOFUS_INSTALLED = os.path.exists(DOFUS_PATH)


RETRO_RELEASE_JSON_PATH = os.path.join(
    ZAAP_PATH, "repositories", "production", "retro", "main", "release.json"
)
if os.path.exists(RETRO_RELEASE_JSON_PATH):
    with open(RETRO_RELEASE_JSON_PATH, "r") as file:
        content: dict = json.load(file)
        if not content.get("location"):
            RETRO_PATH = "DUMMY_RETRO_PATH"
        else:
            RETRO_PATH = os.path.join(
                content["location"],
                "Dofus Retro.exe" if os.name == "nt" else "DofusRetro",
            )
else:
    RETRO_PATH = "DUMMY_RETRO_PATH"
    logger.warning("<!> No Retro path found !")
RETRO_INSTALLED = os.path.exists(RETRO_PATH)


CERTIFICATE_FOLDER_PATH = os.path.join(ZAAP_PATH, "certificate")
API_KEY_FOLDER_PATH = os.path.join(ZAAP_PATH, "keydata")

SETTINGS_PATH = os.path.join(ZAAP_PATH, "Settings")


LAUNCHER_PORT = 26116
RETRO_TEXT_SOCKET_PORT = 26117

GITHUB_URL = "https://github.com/thom493/AnkamaLauncherEmulator"

if os.name == "nt":
    app_config_dir = os.path.join(os.environ["APPDATA"], "AnkamaLauncherEmulator")
else:
    app_config_dir = os.path.join(
        os.environ.get("XDG_CONFIG_HOME", os.path.expanduser("~/.config")),
        "AnkamaLauncherEmulator",
    )
os.makedirs(app_config_dir, exist_ok=True)

ALT_LAUNCHER_DATA_PATH = os.path.join(app_config_dir, "portable_data")
ALT_CERTIFICATE_FOLDER_PATH = os.path.join(ALT_LAUNCHER_DATA_PATH, "certificate")
ALT_API_KEY_FOLDER_PATH = os.path.join(ALT_LAUNCHER_DATA_PATH, "keydata")

os.makedirs(ALT_CERTIFICATE_FOLDER_PATH, exist_ok=True)
os.makedirs(ALT_API_KEY_FOLDER_PATH, exist_ok=True)

APP_CONFIG_PATH = os.path.join(app_config_dir, "config.json")

_BASE_DIR = Path(getattr(sys, "_MEIPASS", Path(__file__).parent.parent))
RESOURCES = _BASE_DIR / "resources"

ANSI_ESCAPE = re.compile(r"\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])")


def _get_local_cytrus_dir() -> str:
    return os.path.join(app_config_dir, "cytrus")


def _get_local_node_dir() -> str:
    return os.path.join(app_config_dir, "node")


def is_cytrus_installed() -> bool:
    if shutil.which("cytrus-v6") is not None:
        return True
    local_cytrus = _get_local_cytrus_dir()
    if os.name == "nt":
        local_exe = os.path.join(local_cytrus, "node_modules", ".bin", "cytrus-v6.cmd")
    else:
        local_exe = os.path.join(local_cytrus, "node_modules", ".bin", "cytrus-v6")
    return os.path.exists(local_exe)


def ensure_cytrus_in_path() -> None:
    """Add local Node and cytrus bins to PATH if they exist."""
    local_node = _get_local_node_dir()
    local_cytrus = _get_local_cytrus_dir()
    local_bin = os.path.join(local_cytrus, "node_modules", ".bin")

    paths_to_add = []
    if os.path.exists(local_node):
        paths_to_add.append(local_node)
    if os.path.exists(local_bin):
        paths_to_add.append(local_bin)

    if paths_to_add:
        current_path = os.environ.get("PATH", "")
        current_parts = current_path.split(os.pathsep)
        new_parts = [p for p in paths_to_add if p not in current_parts]
        if new_parts:
            os.environ["PATH"] = os.pathsep.join(new_parts + current_parts)
