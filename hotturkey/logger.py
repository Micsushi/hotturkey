# logger.py -- Sets up logging so output goes to both the terminal and a log file.
# Other modules import "log" from here and use log.info(), log.debug(), etc.
# Console output is color-coded by tag, file output stays plain text.
# When running detached (no terminal), only the file handler is used.

import logging
import os

from hotturkey.config import STATE_DIR, LOG_FILE

# ANSI color codes for terminal output
COLORS = {
    "[GAMING]":  "\033[95m",   # magenta
    "[WATCHING]": "\033[96m",  # cyan
    "[SESSION]": "\033[93m",   # yellow
    "[BUDGET]":  "\033[92m",   # green
    "[EXTRA]":   "\033[94m",   # blue
    "[POPUP]":   "\033[91m",   # red
    "[START]":   "\033[97m",   # white
    "[STOP]":    "\033[97m",   # white
    "[TRAY]":    "\033[90m",   # gray
    "[IDLE]":    "\033[90m",   # gray
}
RESET = "\033[0m"


class ColorFormatter(logging.Formatter):
    """Adds ANSI colors to console log lines based on the tag (e.g. [GAMING], [BUDGET])."""

    def format(self, record):
        message = super().format(record)
        for tag, color in COLORS.items():
            if tag in message:
                return f"{color}{message}{RESET}"
        return message


class FlushingFileHandler(logging.FileHandler):
    """File handler that flushes after each write so 'Show logs' tail sees new lines immediately."""

    def emit(self, record):
        super().emit(record)
        self.flush()


def setup_logger():
    """Create a logger with two outputs:
    1. Console with colors (when run from terminal)
    2. Plain text file at ~/.hotturkey/hotturkey.log (always, flushed so tail works)"""
    os.makedirs(STATE_DIR, exist_ok=True)

    logger = logging.getLogger("hotturkey")
    logger.setLevel(logging.INFO)

    base_format = "%(asctime)s  %(message)s"
    datefmt = "%Y-%m-%d %H:%M:%S"

    # Console only when we have one (not when running detached in background)
    if os.environ.get("HOTTURKEY_DETACHED") != "1":
        console_handler = logging.StreamHandler()
        console_handler.setFormatter(ColorFormatter(base_format, datefmt=datefmt))
        logger.addHandler(console_handler)

    # File always, with flush so Show logs tail works
    file_handler = FlushingFileHandler(LOG_FILE)
    file_handler.setFormatter(logging.Formatter(base_format, datefmt=datefmt))
    logger.addHandler(file_handler)

    return logger


# This runs once when the module is first imported, creating a shared logger
log = setup_logger()
