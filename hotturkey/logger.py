# logger.py -- Sets up logging so output goes to both the terminal and a log file.
# Logging convention: every line starts with [TAG] for easy grep/parsing.

import logging
import os

from hotturkey.config import STATE_DIR, LOG_FILE, LOG_LEVEL_FILE

# - Green for budget recovery
# - Red for budget consumption
# - Blue for budget full
# - Pastel yellow for [COMMAND]
# - Cyan for everything else
GREEN = "\033[92m"
RED = "\033[91m"
BLUE = "\033[94m"
CYAN = "\033[96m"
PASTEL_YELLOW = "\033[38;5;227m"
RESET = "\033[0m"


class ColorFormatter(logging.Formatter):
    """Adds ANSI colors to console log lines:
    - [BUDGET] with '-'      => red (consumed)
    - [BUDGET] with '+'      => green (recovered)
    - [BUDGET] with ' full ' => blue  (fully refilled)
    - [COMMAND] => pastel yellow (extra, set, reset, start, quit)
    - everything else        => cyan
    """

    def format(self, record):
        # Decide color based on the raw log message
        base_message = record.getMessage()
        color = None
        if "[COMMAND]" in base_message:
            color = PASTEL_YELLOW
        elif "[BUDGET]" in base_message:
            if "| full" in base_message:
                color = BLUE
            elif "budget +" in base_message or "overtime -" in base_message:
                color = GREEN
            elif "budget -" in base_message or "overtime +" in base_message:
                color = RED

        message = super().format(record)

        if color is None:
            return f"{CYAN}{message}{RESET}"

        return f"{color}{message}{RESET}"


class FlushingFileHandler(logging.FileHandler):
    def emit(self, record):
        super().emit(record)
        self.flush()


_current_level_name = "INFO"


def _load_log_level_name() -> str:
    level_name = "INFO"
    try:
        if os.path.exists(LOG_LEVEL_FILE):
            with open(LOG_LEVEL_FILE, "r") as f:
                raw = f.read().strip()
            if raw:
                level_name = raw.upper()
    except OSError:
        pass
    return level_name


def setup_logger():
    """Create a logger with two outputs:
    1. Terminal
    2. At ~/.hotturkey/hotturkey.log (flushed so tail works)"""
    os.makedirs(STATE_DIR, exist_ok=True)

    global _current_level_name

    logger = logging.getLogger("hotturkey")

    _current_level_name = _load_log_level_name()
    logger.setLevel(getattr(logging, _current_level_name, logging.INFO))

    base_format = "%(asctime)s  %(message)s"
    datefmt = "%Y-%m-%d %H:%M:%S"

    if os.environ.get("HOTTURKEY_DETACHED") != "1":
        console_handler = logging.StreamHandler()
        console_handler.setFormatter(ColorFormatter(base_format, datefmt=datefmt))
        logger.addHandler(console_handler)

    log_file_path = LOG_FILE
    if os.environ.get("CI") == "true":
        ci_log_dir = os.path.join(os.getcwd(), ".hotturkey-ci")
        try:
            os.makedirs(ci_log_dir, exist_ok=True)
            log_file_path = os.path.join(ci_log_dir, "hotturkey.log")
        except OSError:
            log_file_path = LOG_FILE

    try:
        file_handler = FlushingFileHandler(log_file_path)
        file_handler.setFormatter(ColorFormatter(base_format, datefmt=datefmt))
        logger.addHandler(file_handler)
    except OSError:
        pass

    return logger


# This runs once when the module is first imported, creating a shared logger
log = setup_logger()


def refresh_log_level_from_disk():
    global _current_level_name

    new_name = _load_log_level_name()
    if new_name == _current_level_name:
        return

    new_level = getattr(logging, new_name, logging.INFO)
    log.setLevel(new_level)
    old = _current_level_name
    _current_level_name = new_name
    log.info(f"[COMMAND] loglevel: old={old} new={new_name}")


def log_event(tag, message=None, **kwargs):
    if message is not None:
        log.info(f"[{tag}] {message}")
    else:
        parts = " ".join(f"{k}={v}" for k, v in kwargs.items())
        log.info(f"[{tag}] {parts}")
