"""Global proxy library with per-account assignment.

v2 format:
{
  "version": 2,
  "proxies": {
    "uuid-1": {"name": "...", "url": "socks5://...", "exit_ip": null, "tested_at": null}
  },
  "assignments": {
    "login@email.com": "uuid-1"
  }
}
"""

import json
import logging
import os
import uuid
from dataclasses import dataclass
from datetime import datetime

from ankama_launcher_emulator.consts import app_config_dir

logger = logging.getLogger()

PROXY_STORE_PATH = os.path.join(app_config_dir, "proxies.json")


@dataclass
class ProxyEntry:
    name: str
    url: str
    exit_ip: str | None = None
    tested_at: str | None = None

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "url": self.url,
            "exit_ip": self.exit_ip,
            "tested_at": self.tested_at,
        }

    @staticmethod
    def from_dict(d: dict) -> "ProxyEntry":
        return ProxyEntry(
            name=d.get("name", ""),
            url=d.get("url", ""),
            exit_ip=d.get("exit_ip"),
            tested_at=d.get("tested_at"),
        )


class ProxyStore:
    """Global proxy library with per-account assignment."""

    def __init__(self):
        self._proxies: dict[str, ProxyEntry] = {}
        self._assignments: dict[str, str] = {}
        self._load()

    def _load(self) -> None:
        if not os.path.exists(PROXY_STORE_PATH):
            return
        try:
            with open(PROXY_STORE_PATH, "r") as f:
                raw = json.load(f)
        except (json.JSONDecodeError, OSError) as err:
            logger.warning(f"[PROXY_STORE] Failed to load: {err}")
            return

        if raw.get("version") == 2:
            for pid, pdata in raw.get("proxies", {}).items():
                self._proxies[pid] = ProxyEntry.from_dict(pdata)
            self._assignments = dict(raw.get("assignments", {}))
        else:
            self._migrate_v1(raw)

    def _migrate_v1(self, raw: dict) -> None:
        """Migrate v1 format: {login: {proxy_url, exit_ip, validated_at}}."""
        for login, entry in raw.items():
            if not isinstance(entry, dict) or "proxy_url" not in entry:
                continue
            proxy_url = entry["proxy_url"]
            pid = str(uuid.uuid4())
            self._proxies[pid] = ProxyEntry(
                name=f"Migrated ({proxy_url[:30]})",
                url=proxy_url,
                exit_ip=entry.get("exit_ip"),
                tested_at=entry.get("validated_at"),
            )
            self._assignments[login] = pid
        self._save()
        logger.info(f"[PROXY_STORE] Migrated {len(self._proxies)} proxies from v1")

    def _save(self) -> None:
        data = {
            "version": 2,
            "proxies": {pid: p.to_dict() for pid, p in self._proxies.items()},
            "assignments": self._assignments,
        }
        try:
            with open(PROXY_STORE_PATH, "w") as f:
                json.dump(data, f, indent=2)
        except OSError as err:
            logger.warning(f"[PROXY_STORE] Failed to save: {err}")

    # --- Proxy CRUD ---

    def list_proxies(self) -> dict[str, ProxyEntry]:
        return dict(self._proxies)

    def add_proxy(self, name: str, url: str) -> str:
        pid = str(uuid.uuid4())
        self._proxies[pid] = ProxyEntry(name=name, url=url)
        self._save()
        return pid

    def update_proxy(
        self,
        proxy_id: str,
        name: str | None = None,
        url: str | None = None,
        exit_ip: str | None = ...,  # type: ignore[assignment]
        tested_at: str | None = ...,  # type: ignore[assignment]
    ) -> None:
        entry = self._proxies.get(proxy_id)
        if not entry:
            return
        if name is not None:
            entry.name = name
        if url is not None:
            entry.url = url
        if exit_ip is not ...:
            entry.exit_ip = exit_ip  # type: ignore[comparison-overlap]
        if tested_at is not ...:
            entry.tested_at = tested_at  # type: ignore[comparison-overlap]
        self._save()

    def remove_proxy(self, proxy_id: str) -> None:
        self._proxies.pop(proxy_id, None)
        self._assignments = {
            login: pid for login, pid in self._assignments.items() if pid != proxy_id
        }
        self._save()

    def get_proxy(self, proxy_id: str) -> ProxyEntry | None:
        return self._proxies.get(proxy_id)

    # --- Assignment ---

    def assign_proxy(self, login: str, proxy_id: str | None) -> None:
        if proxy_id is None:
            self._assignments.pop(login, None)
        else:
            self._assignments[login] = proxy_id
        self._save()

    def get_assignment(self, login: str) -> str | None:
        return self._assignments.get(login)

    def get_proxy_url(self, login: str) -> str | None:
        pid = self._assignments.get(login)
        if pid:
            entry = self._proxies.get(pid)
            if entry:
                return entry.url
        return None

    # --- Compat wrappers (used by existing callers) ---

    def save_validated(
        self, login: str, proxy_url: str, exit_ip: str | None = None
    ) -> None:
        """Compat: find or create proxy entry, assign to login."""
        # Find existing proxy with same URL
        for pid, entry in self._proxies.items():
            if entry.url == proxy_url:
                entry.exit_ip = exit_ip
                entry.tested_at = datetime.now().isoformat()
                self._assignments[login] = pid
                self._save()
                return
        # Create new
        pid = self.add_proxy(name=proxy_url[:40], url=proxy_url)
        if exit_ip:
            self.update_proxy(pid, exit_ip=exit_ip)
        self.update_proxy(pid, tested_at=datetime.now().isoformat())
        self._assignments[login] = pid
        self._save()

    def test_proxy(self, proxy_id: str) -> str | None:
        """Test proxy and store result. Returns exit IP or None on failure."""
        from ankama_launcher_emulator.utils.proxy import verify_proxy_ip

        entry = self._proxies.get(proxy_id)
        if not entry:
            return None
        try:
            exit_ip = verify_proxy_ip(entry.url)
            entry.exit_ip = exit_ip
            entry.tested_at = datetime.now().isoformat()
            self._save()
            return exit_ip
        except Exception as err:
            logger.warning(f"[PROXY_STORE] Test failed for {proxy_id}: {err}")
            return None
