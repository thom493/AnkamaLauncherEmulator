import logging
from typing import TypedDict

import requests

from ankama_launcher_emulator._version import get_version

logger = logging.getLogger()

GITHUB_API_LATEST = (
    "https://api.github.com/repos/thom493/AnkamaLauncherEmulator/releases/latest"
)


class UpdateInfo(TypedDict):
    version: str
    html_url: str
    download_url: str | None


def _current_version() -> str:
    return get_version()


def _parse_semver(v: str) -> tuple[int, ...]:
    """Split a version string into a tuple of ints for comparison."""
    parts = v.lstrip("vV").split(".")
    result: list[int] = []
    for part in parts:
        try:
            result.append(int(part))
        except ValueError:
            break
    return tuple(result)


def is_version_greater(remote: str, local: str) -> bool:
    """Return True if *remote* is strictly greater than *local*."""
    return _parse_semver(remote) > _parse_semver(local)


def check_for_update() -> UpdateInfo | None:
    """Query GitHub for the latest release and compare with the installed version.

    Returns ``None`` when no update is available or the check fails.
    """
    local = _current_version()
    try:
        resp = requests.get(GITHUB_API_LATEST, timeout=10)
        resp.raise_for_status()
        data = resp.json()
    except Exception as exc:
        logger.warning("[UPDATER] Failed to fetch latest release: %s", exc)
        return None

    tag = data.get("tag_name", "")
    if not tag:
        logger.warning("[UPDATER] No tag_name in release response")
        return None

    remote = tag.lstrip("vV")
    if not is_version_greater(remote, local):
        return None

    html_url = data.get("html_url", "")
    assets = data.get("assets", [])
    download_url: str | None = None
    if assets:
        download_url = assets[0].get("browser_download_url")

    logger.info("[UPDATER] Update available: %s → %s", local, remote)
    return UpdateInfo(version=remote, html_url=html_url, download_url=download_url)
