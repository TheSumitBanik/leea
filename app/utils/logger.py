from loguru import logger
import os
import sys

# Configure Loguru: console + rotating file handler
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
LOG_DIR = os.getenv("LOG_DIR", "output/logs")
LOG_FILE = os.path.join(LOG_DIR, "leea.log")

# Ensure log directory exists
os.makedirs(LOG_DIR, exist_ok=True)

# Remove default logger and set up sinks
logger.remove()
logger.add(sys.stderr, level=LOG_LEVEL, enqueue=True, backtrace=True, diagnose=False)
logger.add(
    LOG_FILE,
    rotation="20 MB",
    retention="14 days",
    compression="zip",
    level=LOG_LEVEL,
    enqueue=True,
)

__all__ = ["logger"]
