import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

LOG_DIR = Path(__file__).resolve().parent.parent
LOG_FILE = "webui.log"
MAX_BYTES = 10_000_000
BACKUP_COUNT = 5

_configured = False


def configure_file_logging(level: str = "INFO") -> None:
    global _configured
    if _configured:
        return
    _configured = True
    resolved_level = getattr(logging, level.upper(), logging.INFO)
    handler = RotatingFileHandler(
        LOG_DIR / LOG_FILE,
        maxBytes=MAX_BYTES,
        backupCount=BACKUP_COUNT,
        encoding="utf-8",
    )
    handler.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s")
    )
    logger = logging.getLogger("uvicorn.error")
    logger.addHandler(handler)
    logger.setLevel(resolved_level)
