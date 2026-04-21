import logging
import os

from ankama_launcher_emulator.consts import app_config_dir
from ankama_launcher_emulator.gui import run_gui

logger = logging.getLogger()
logger.setLevel(logging.DEBUG)

_fmt = logging.Formatter("%(asctime)s %(levelname)s [%(name)s] %(message)s")

stream = logging.StreamHandler()
stream.setLevel(logging.INFO)
stream.setFormatter(_fmt)
logger.addHandler(stream)

_log_path = os.path.join(app_config_dir, "ankalt_debug.log")
file_handler = logging.FileHandler(_log_path, mode="a", encoding="utf-8")
file_handler.setLevel(logging.DEBUG)
file_handler.setFormatter(_fmt)
logger.addHandler(file_handler)
logger.info("=== launcher start, debug log: %s ===", _log_path)

if __name__ in {"__main__", "__mp_main__"}:
    run_gui()
