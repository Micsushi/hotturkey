# logger.py -- Sets up logging so output goes to both the terminal and a log file.
# Other modules import "log" from here and use log.info(), log.debug(), etc.
# Console output is color-coded by tag, file output stays plain text.
# When running detached (no terminal), only the file handler is used.

import logging
import os

from hotturkey.config import STATE_DIR, LOG_FILE

# Simplified ANSI colors:
# - Green for budget recovery
# - Red for budget consumption
# - Cyan for everything else
GREEN = "\033[92m"
RED = "\033[91m"
CYAN = "\033[96m"
RESET = "\033[0m"


class ColorFormatter(logging.Formatter):
    """Adds ANSI colors to console log lines:
    - [BUDGET] with '-' => red (consumed)
    - [BUDGET] with '+' => green (recovered)
    - everything else    => cyan
    """

    def format(self, record):
        # Decide color based on the raw log message (without timestamp) so
        # date dashes like "2026-03-04" don't trick us into thinking it's a
        # budget consumption.
        base_message = record.getMessage()
        color = None
        if "[BUDGET]" in base_message:
            if "+" in base_message:
                color = GREEN
            elif "-" in base_message:
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

    # File with colors so Show logs (PowerShell tail) displays them
    file_handler = FlushingFileHandler(LOG_FILE)
    file_handler.setFormatter(ColorFormatter(base_format, datefmt=datefmt))
    logger.addHandler(file_handler)

    return logger


# This runs once when the module is first imported, creating a shared logger
log = setup_logger()
