import json
import logging
import os
from datetime import datetime

from ankama_launcher_emulator.consts import app_config_dir

logger = logging.getLogger()

PROXY_STORE_PATH = os.path.join(app_config_dir, "proxies.json")


class ProxyStore:
    """Persist proxy-account validation mappings across sessions."""

    def __init__(self):
        self._data: dict[str, dict] = self._load()

    def _load(self) -> dict[str, dict]:
        if not os.path.exists(PROXY_STORE_PATH):
            return {}
        try:
            with open(PROXY_STORE_PATH, "r") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError) as err:
            logger.warning(f"[PROXY_STORE] Failed to load: {err}")
            return {}

    def _save(self) -> None:
        try:
            with open(PROXY_STORE_PATH, "w") as f:
                json.dump(self._data, f, indent=2)
        except OSError as err:
            logger.warning(f"[PROXY_STORE] Failed to save: {err}")

    def get_proxy(self, login: str) -> str | None:
        entry = self._data.get(login)
        if entry:
            return entry.get("proxy_url")
        return None

    def get_entry(self, login: str) -> dict | None:
        return self._data.get(login)

    def save_validated(
        self, login: str, proxy_url: str, exit_ip: str | None = None
    ) -> None:
        self._data[login] = {
            "proxy_url": proxy_url,
            "exit_ip": exit_ip,
            "validated_at": datetime.now().isoformat(),
        }
        self._save()

    def remove(self, login: str) -> None:
        if login in self._data:
            del self._data[login]
            self._save()

    def all_entries(self) -> dict[str, dict]:
        return dict(self._data)
