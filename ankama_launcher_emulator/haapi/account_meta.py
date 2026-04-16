"""Account metadata store for managed accounts.

Stores per-account metadata (hm1, source, alias) that doesn't belong
in Zaap's encrypted keydata files.

File: ~/.ankama_launcher_emulator/account_meta.json
"""

import json
import logging
import os
from datetime import datetime

from ankama_launcher_emulator.consts import app_config_dir

logger = logging.getLogger()

META_PATH = os.path.join(app_config_dir, "account_meta.json")


class AccountMeta:
    """Persist extra per-account metadata across sessions."""

    def __init__(self):
        self._data: dict[str, dict] = self._load()

    def _load(self) -> dict[str, dict]:
        if not os.path.exists(META_PATH):
            return {}
        try:
            with open(META_PATH, "r") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError) as err:
            logger.warning(f"[ACCOUNT_META] Failed to load: {err}")
            return {}

    def _save(self) -> None:
        try:
            with open(META_PATH, "w") as f:
                json.dump(self._data, f, indent=2)
        except OSError as err:
            logger.warning(f"[ACCOUNT_META] Failed to save: {err}")

    def get(self, login: str) -> dict | None:
        return self._data.get(login)

    def get_hm1(self, login: str) -> str | None:
        entry = self._data.get(login)
        if entry:
            return entry.get("hm1")
        return None

    def get_hm2(self, login: str) -> str | None:
        hm1 = self.get_hm1(login)
        if hm1:
            return hm1[::-1]
        return None

    def set_meta(
        self,
        login: str,
        source: str = "managed",
        alias: str | None = None,
        hm1: str | None = None,
    ) -> None:
        entry = self._data.get(login, {})
        entry["source"] = source
        if alias is not None:
            entry["alias"] = alias
        if hm1 is not None:
            entry["hm1"] = hm1
        if "added_at" not in entry:
            entry["added_at"] = datetime.now().isoformat()
        self._data[login] = entry
        self._save()

    def set_hm1(self, login: str, hm1: str | None) -> None:
        entry = self._data.get(login, {})
        if hm1 is None:
            entry.pop("hm1", None)
        else:
            entry["hm1"] = hm1
        self._data[login] = entry
        self._save()

    def remove(self, login: str) -> None:
        if login in self._data:
            del self._data[login]
            self._save()

    def all_entries(self) -> dict[str, dict]:
        return dict(self._data)
