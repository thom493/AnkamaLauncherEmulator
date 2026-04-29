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
    ) -> None:
        entry = self._data.get(login, {})
        entry["source"] = source
        if alias is not None:
            entry["alias"] = alias
        if "added_at" not in entry:
            entry["added_at"] = datetime.now().isoformat()
        
        self._data[login] = entry
        self.generate_fake_profile(login)  # Ensure fake profile exists
        self._save()

    def generate_fake_profile(self, login: str) -> None:
        entry = self._data.get(login, {})
        if not entry.get("fake_uuid"):
            import uuid, hashlib, random, string
            fake_uuid = str(uuid.uuid4())
            fake_machine_id = hashlib.sha256(fake_uuid.encode('utf-8')).hexdigest()
            # Simulate Windows 10, 16gb Machine
            machine_infos = [
                "x64",
                "win32",
                fake_machine_id,
                "user",
                "10",
                "16384"
            ]
            fake_hm1 = hashlib.sha256("".join(machine_infos).encode("utf-8")).hexdigest()[:32]
            
            entry["fake_uuid"] = fake_uuid
            entry["fake_hm1"] = fake_hm1
            entry["fake_hm2"] = fake_hm1[::-1]
            entry["fake_hostname"] = "DESKTOP-" + "".join(random.choices(string.ascii_uppercase + string.digits, k=7))
            entry.setdefault("portable_mode", False)
            entry.setdefault("proxy_url", None)
            
            self._data[login] = entry
            self._save()

    def set_portable_mode(self, login: str, portable: bool) -> None:
        entry = self._data.get(login, {})
        entry["portable_mode"] = portable
        self._data[login] = entry
        self._save()
        # Portable mode requires a fake hardware fingerprint — generate one
        # on first toggle so get_crypto_context never falls back to real
        # Device.getUUID() with the ALT folder (would hash-mismatch every read).
        if portable:
            self.generate_fake_profile(login)

    def set_imported_portable_profile(
        self,
        login: str,
        *,
        alias: str | None,
        fake_uuid: str,
        fake_hm1: str,
        fake_hm2: str,
        fake_hostname: str,
        proxy_url: str | None,
        cert_validated_proxy_url: str | None,
    ) -> None:
        entry = self._data.get(login, {})
        entry["source"] = "managed"
        if alias is not None:
            entry["alias"] = alias
        if "added_at" not in entry:
            entry["added_at"] = datetime.now().isoformat()
        entry["portable_mode"] = True
        entry["fake_uuid"] = fake_uuid
        entry["fake_hm1"] = fake_hm1
        entry["fake_hm2"] = fake_hm2
        entry["fake_hostname"] = fake_hostname
        entry["proxy_url"] = proxy_url
        if cert_validated_proxy_url is not None:
            entry["cert_validated_proxy_url"] = cert_validated_proxy_url
        else:
            entry.pop("cert_validated_proxy_url", None)
        self._data[login] = entry
        self._save()

    def set_proxy(self, login: str, proxy_url: str | None) -> None:
        entry = self._data.get(login, {})
        entry["proxy_url"] = proxy_url
        self._data[login] = entry
        self._save()

    def record_launch_state(
        self,
        login: str,
        portable_mode: bool,
        proxy_url: str | None,
        interface_ip: str | None,
    ) -> None:
        entry = self._data.get(login, {})
        entry["last_launch_portable_mode"] = portable_mode
        entry["last_launch_proxy_url"] = proxy_url
        entry["last_launch_interface_ip"] = interface_ip
        self._data[login] = entry
        self._save()

    def state_changed_since_last_launch(
        self,
        login: str,
        portable_mode: bool,
        proxy_url: str | None,
        interface_ip: str | None,
    ) -> bool:
        entry = self._data.get(login) or {}
        if "last_launch_portable_mode" not in entry:
            return True
        return (
            entry.get("last_launch_portable_mode") != portable_mode
            or entry.get("last_launch_proxy_url") != proxy_url
            or entry.get("last_launch_interface_ip") != interface_ip
        )

    def record_cert_validated(self, login: str, proxy_url: str | None) -> None:
        entry = self._data.get(login, {})
        entry["cert_validated_proxy_url"] = proxy_url
        self._data[login] = entry
        self._save()

    def cert_proxy_changed(self, login: str, proxy_url: str | None) -> bool:
        """True if current proxy differs from the one used when cert was last validated."""
        entry = self._data.get(login) or {}
        if "cert_validated_proxy_url" not in entry:
            return False  # no record yet — let reactive 403 handle it
        return entry.get("cert_validated_proxy_url") != proxy_url

    def is_proxy_used(self, proxy_url: str, exclude_login: str | None = None) -> bool:
        for _login, entry in self._data.items():
            if exclude_login and _login == exclude_login:
                continue
            if entry.get("proxy_url") == proxy_url:
                return True
        return False


    def repair_corrupt_entries(self) -> int:
        """Heal entries with portable_mode=True but missing/falsy fake_uuid.

        Such entries cannot resolve to ALT folder credentials and would skip
        at load. Regenerates the fake profile in place. Returns count repaired.
        """
        repaired = 0
        for login, entry in list(self._data.items()):
            if entry.get("portable_mode") and not entry.get("fake_uuid"):
                self.generate_fake_profile(login)
                logger.info(f"[REPAIR] {login}: generated missing fake profile for portable entry")
                repaired += 1
        return repaired

    def set_hm1(self, login: str, hm1: str | None) -> None:
        pass # Obsolete: Handled by generate_fake_profile

    def remove(self, login: str) -> None:
        if login in self._data:
            del self._data[login]
            self._save()

    def all_entries(self) -> dict[str, dict]:
        return dict(self._data)
