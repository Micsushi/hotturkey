# logger.py -- Sets up logging so output goes to both the terminal and a log file.
# Other modules import "log" from here and use log.info(), log.debug(), etc.
# Console output is color-coded by tag, file output stays plain text.
# When running detached (no terminal), only the file handler is used.
#
# Logging convention: every line starts with [TAG] for easy grep/parsing.
# Standard tags: START, STOP, BUDGET, COMMAND (extra/set/reset/start/quit), SESSION, IDLE,
# FOCUS (e.g. "other apps" when leaving a tracked window), GAMING, WATCHING, BONUS, POPUP, TRAY, PERF, DEBUG.
# Use log_event(tag, message="...") for human-readable lines, or log_event(tag, key=val, ...) for key=value.

import logging
import os

from hotturkey.config import STATE_DIR, LOG_FILE, LOG_LEVEL_FILE

# Simplified ANSI colors:
# - Green for budget recovery
# - Red for budget consumption
# - Blue for "full budget" lines
# - Pastel yellow for [COMMAND] (user actions: extra, set, reset, start, quit)
# - Cyan for everything else
GREEN = "\033[92m"
RED = "\033[91m"
BLUE = "\033[94m"
CYAN = "\033[96m"
# Pastel yellow (256-color palette)
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
        # Decide color based on the raw log message (without timestamp) so
        # date dashes like "2026-03-04" don't trick us into thinking it's a
        # budget consumption.
        base_message = record.getMessage()
        color = None
        if "[COMMAND]" in base_message:
            color = PASTEL_YELLOW
        elif "[BUDGET]" in base_message:
            if " full " in base_message:
                color = BLUE
            # budget + or overtime - = repaying (green); budget - or overtime + = consuming (red)
            elif "budget +" in base_message or "overtime -" in base_message:
                color = GREEN
            elif "budget -" in base_message or "overtime +" in base_message:
                color = RED

        message = super().format(record)

        if color is None:
            # All non-budget logs: cyan
            return f"{CYAN}{message}{RESET}"

        return f"{color}{message}{RESET}"


class FlushingFileHandler(logging.FileHandler):
    """File handler that flushes after each write so 'Show logs' tail sees new lines immediately."""

    def emit(self, record):
        super().emit(record)
        self.flush()


_current_level_name = "INFO"


def _load_log_level_name() -> str:
    """Return the logging level *name* to use, based on LOG_LEVEL_FILE if present.

    Defaults to 'INFO' for normal, concise logs. Accepts standard level names
    like DEBUG, INFO, WARNING, ERROR (case-insensitive).
    """
    level_name = "INFO"
    try:
        if os.path.exists(LOG_LEVEL_FILE):
            with open(LOG_LEVEL_FILE, "r") as f:
                raw = f.read().strip()
            if raw:
                level_name = raw.upper()
    except OSError:
        # Fall back to default on any read error.
        pass

    return level_name


def _load_log_level() -> int:
    """Return the numeric logging level to use based on LOG_LEVEL_FILE."""
    level_name = _load_log_level_name()
    return getattr(logging, level_name, logging.INFO)


def setup_logger():
    """Create a logger with two outputs:
    1. Console with colors (when run from terminal)
    2. Plain text file at ~/.hotturkey/hotturkey.log (always, flushed so tail works)"""
    os.makedirs(STATE_DIR, exist_ok=True)

    global _current_level_name

    logger = logging.getLogger("hotturkey")
    # Log level is user-tunable via LOG_LEVEL_FILE so the CLI can flip between
    # INFO (normal) and DEBUG (perf troubleshooting) without code changes.
    _current_level_name = _load_log_level_name()
    logger.setLevel(getattr(logging, _current_level_name, logging.INFO))

    base_format = "%(asctime)s  %(message)s"
    datefmt = "%Y-%m-%d %H:%M:%S"

    # Console only when we have one (not when running detached in background)
    if os.environ.get("HOTTURKEY_DETACHED") != "1":
        console_handler = logging.StreamHandler()
        console_handler.setFormatter(ColorFormatter(base_format, datefmt=datefmt))
        logger.addHandler(console_handler)

    # File with colors so Show logs (PowerShell tail) displays them.
    # In CI, use a workspace-local log file so tests don't write to the
    # runner's real home directory. GitHub Actions sets CI=true.
    log_file_path = LOG_FILE
    if os.environ.get("CI") == "true":
        ci_log_dir = os.path.join(os.getcwd(), ".hotturkey-ci")
        try:
            os.makedirs(ci_log_dir, exist_ok=True)
            log_file_path = os.path.join(ci_log_dir, "hotturkey.log")
        except OSError:
            # If we can't create a CI log dir, fall back to the default path.
            log_file_path = LOG_FILE

    try:
        file_handler = FlushingFileHandler(log_file_path)
        file_handler.setFormatter(ColorFormatter(base_format, datefmt=datefmt))
        logger.addHandler(file_handler)
    except OSError:
        # Fall back to console-only logging if the log file cannot be opened.
        pass

    return logger


# This runs once when the module is first imported, creating a shared logger
log = setup_logger()


def refresh_log_level_from_disk():
    """Reload log level from LOG_LEVEL_FILE if it changed.

    Called periodically by the running app so commands like `hotturkey morelog`
    take effect without restarting the background process.
    """
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
    """Log a single line. If message is set, logs [TAG] message (human-readable).
    Otherwise logs [TAG] key=value key=value for parseable output."""
    if message is not None:
        log.info(f"[{tag}] {message}")
    else:
        parts = " ".join(f"{k}={v}" for k, v in kwargs.items())
        log.info(f"[{tag}] {parts}")
