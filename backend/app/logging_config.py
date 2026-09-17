import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

from app.config import Settings

LOG_DIR = Path(__file__).resolve().parent.parent

MAX_BYTES = 10_000_000
BACKUP_COUNT = 5

_configured = False


def configure_file_logging(settings: Settings) -> None:
    global _configured
    if _configured:
        return
    _configured = True

    level = getattr(logging, settings.log_level.upper(), logging.INFO)
    handler = RotatingFileHandler(
        LOG_DIR / settings.log_file,
        maxBytes=MAX_BYTES,
        backupCount=BACKUP_COUNT,
        encoding="utf-8",
    )
    handler.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s")
    )
    logger = logging.getLogger("uvicorn.error")
    logger.addHandler(handler)
    logger.setLevel(level)
