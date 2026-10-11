import logging
import os
import sys

LOG_FILE = os.path.join(os.path.expanduser("~"), ".local", "share", "intermux", "intermux.log")


def setup() -> logging.Logger:
    """Console gets INFO and above, the log file gets everything including executed commands."""
    logger = logging.getLogger("intermux")
    if logger.handlers:
        return logger
    logger.setLevel(logging.DEBUG)

    console = logging.StreamHandler(sys.stderr)
    console.setLevel(logging.INFO)
    console.setFormatter(logging.Formatter("%(message)s"))
    logger.addHandler(console)

    try:
        os.makedirs(os.path.dirname(LOG_FILE), exist_ok=True)
        file = logging.FileHandler(LOG_FILE, encoding="utf-8")
    except OSError as exc:
        logger.warning("Cannot open log file %s: %s", LOG_FILE, exc)
    else:
        file.setLevel(logging.DEBUG)
        file.setFormatter(logging.Formatter(
            "%(asctime)s [%(levelname)s] %(name)s: %(message)s", "%Y-%m-%d %H:%M:%S"))
        logger.addHandler(file)

    return logger
