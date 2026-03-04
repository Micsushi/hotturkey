import logging
import os

from hotturkey.config import STATE_DIR, LOG_FILE


def setup_logger():
    """Create a logger that writes to both console and ~/.hotturkey/hotturkey.log."""
    os.makedirs(STATE_DIR, exist_ok=True)

    logger = logging.getLogger("hotturkey")
    logger.setLevel(logging.INFO)

    formatter = logging.Formatter("%(asctime)s  %(message)s", datefmt="%Y-%m-%d %H:%M:%S")

    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)

    file_handler = logging.FileHandler(LOG_FILE)
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

    return logger


log = setup_logger()
