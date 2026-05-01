import json
import logging
import os

from ankama_launcher_emulator.consts import APP_CONFIG_PATH

logger = logging.getLogger()

_VALID_GAME_KEYS = {"dofus3", "retro"}


def _load_app_config() -> dict:
    if not os.path.exists(APP_CONFIG_PATH):
        return {}
    try:
        with open(APP_CONFIG_PATH, "r") as file:
            data = json.load(file)
    except (json.JSONDecodeError, OSError) as err:
        logger.warning(f"[APP_CONFIG] Failed to load: {err}")
        return {}
    return data if isinstance(data, dict) else {}


def _save_app_config(config: dict) -> None:
    try:
        with open(APP_CONFIG_PATH, "w") as file:
            json.dump(config, file, indent=2)
    except OSError as err:
        logger.warning(f"[APP_CONFIG] Failed to save: {err}")


def get_last_selected_game() -> str | None:
    game = _load_app_config().get("last_selected_game")
    if game in _VALID_GAME_KEYS:
        return game
    return None


def set_last_selected_game(game: str) -> None:
    if game not in _VALID_GAME_KEYS:
        raise ValueError(f"Unsupported game key: {game}")
    config = _load_app_config()
    config["last_selected_game"] = game
    _save_app_config(config)


def get_debug_mode() -> bool:
    return bool(_load_app_config().get("debug_mode", False))


def set_debug_mode(enabled: bool) -> None:
    config = _load_app_config()
    config["debug_mode"] = bool(enabled)
    _save_app_config(config)


def get_check_for_updates() -> bool:
    return bool(_load_app_config().get("check_for_updates", True))


def set_check_for_updates(enabled: bool) -> None:
    config = _load_app_config()
    config["check_for_updates"] = bool(enabled)
    _save_app_config(config)


def get_skipped_version() -> str | None:
    version = _load_app_config().get("skipped_version")
    return version if isinstance(version, str) else None


def set_skipped_version(version: str | None) -> None:
    config = _load_app_config()
    if version is None:
        config.pop("skipped_version", None)
    else:
        config["skipped_version"] = version
    _save_app_config(config)
