import json
import os
from pathlib import Path

from ankama_launcher_emulator.utils.asar_parser import read_file_from_asar


def get_zaap_version():
    asar_path = Path(
        os.path.join(
            os.getenv("programfiles", ""),
            "Ankama",
            "Ankama Launcher",
            "resources",
            "app.asar",
        )
    )

    zaapVersion = "none"
    try:
        data = read_file_from_asar(asar_path, "package.json")
        pkg = json.loads(data.decode("utf-8"))
        zaapVersion = pkg.get("version")
    except (FileNotFoundError, ValueError, KeyError, json.JSONDecodeError):
        pass

    if zaapVersion == "none" or not zaapVersion:
        zaapVersion = "3.12.19"

    return zaapVersion


ZAAP_VERSION = get_zaap_version()
