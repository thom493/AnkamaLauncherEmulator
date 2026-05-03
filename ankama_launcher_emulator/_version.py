"""Application version resolution.

Priority:
1. Git describe output (if inside a git repository).
2. Installed package metadata (hatch-vcs derived).
3. Static fallback "0.0.0".
"""

import logging
import os
import subprocess
from importlib.metadata import PackageNotFoundError, version

logger = logging.getLogger()


_GIT_DESIBE_CMD = ["git", "describe", "--tags", "always", "--dirty"]


def _try_git_describe() -> str | None:
    """Return the raw git describe string, or None if unavailable."""
    here = os.path.dirname(os.path.abspath(__file__))
    # Walk up looking for .git; avoids assuming cwd is the repo root.
    root = here
    while True:
        if os.path.isdir(os.path.join(root, ".git")):
            break
        parent = os.path.dirname(root)
        if parent == root:
            return None
        root = parent

    try:
        result = subprocess.run(
            ["git", "describe", "--tags", "--always", "--dirty"],
            cwd=root,
            capture_output=True,
            text=True,
            check=True,
        )
        raw = result.stdout.strip()
        return raw if raw else None
    except Exception:
        return None


def get_version() -> str:
    """Return the application version string."""
    # Prefer installed package metadata (hatch-vcs derived) for consistency
    # between normal runs and PyInstaller bundles.
    try:
        return version("ankama_launcher_emulator")
    except PackageNotFoundError:
        pass

    git_version = _try_git_describe()
    if git_version:
        # Normalize: strip leading v/V for consistency.
        if git_version.startswith(("v", "V")):
            git_version = git_version[1:]
        return git_version

    logger.warning("[_VERSION] Package not installed and not in a git repo")
    return "0.0.0"
