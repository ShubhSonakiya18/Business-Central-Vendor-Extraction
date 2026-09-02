import logging
import os
from logging.handlers import RotatingFileHandler


LOG_DIR = "logs"
LOG_FILE = os.path.join(LOG_DIR, "app.log")

# Create logs directory if it doesn't exist
os.makedirs(LOG_DIR, exist_ok=True)

logger = logging.getLogger("application")

logger.setLevel(logging.INFO)

logger.propagate = False


formatter = logging.Formatter(
    fmt=(
        "%(asctime)s | "
        "%(levelname)s | "
        "%(name)s | "
        "%(filename)s:%(lineno)d | "
        "%(message)s"
    ),
    datefmt="%Y-%m-%d %H:%M:%S",
)


file_handler = RotatingFileHandler(
    filename=LOG_FILE,
    maxBytes=10 * 1024 * 1024,  # 10 MB
    backupCount=5,
    encoding="utf-8",
)

file_handler.setLevel(logging.INFO)
file_handler.setFormatter(formatter)


# console_handler = logging.StreamHandler()

# console_handler.setLevel(logging.INFO)
# console_handler.setFormatter(formatter)


if not logger.handlers:
    logger.addHandler(file_handler)
    # logger.addHandler(console_handler)

def log_info(message: str):
    """Log informational message."""
    logger.info(message)


def log_warning(message: str):
    """Log warning message."""
    logger.warning(message)


def log_error(message: str):
    """Log error message."""
    logger.error(message)


def log_exception(message: str):
    """
    Log error message along with exception traceback.
    Should be used inside an except block.
    """
    logger.exception(message)


def log_debug(message: str):
    """Log debug message."""
    logger.debug(message)