import logging
import re
from logging.handlers import RotatingFileHandler
from pathlib import Path

from app.config import Settings
from toolbox.db import restrict_permissions

LOG_DIR = Path(__file__).resolve().parent.parent

MAX_BYTES = 10_000_000
BACKUP_COUNT = 5

_configured = False

REDACTED = "[REDACTED]"

# Secrets that must never reach a log file or console, whatever code path
# logged them (tool errors, upstream exception text, request dumps).
_PLAIN_SECRET_PATTERNS = [
    re.compile(r"sk-[A-Za-z0-9_-]{16,}"),
    re.compile(r"AIza[0-9A-Za-z_-]{30,}"),
    re.compile(r"Bearer\s+[A-Za-z0-9._~+/=-]{8,}"),
    re.compile(r"ya29\.[0-9A-Za-z_-]+"),
    re.compile(r"1//[0-9A-Za-z_-]{20,}"),
    re.compile(r"xox[abpr]-[0-9A-Za-z-]+"),
]
# JSON-style "key": "value" -- keep the key, drop the value.
_KEYED_SECRET = re.compile(
    r'"(password|api_key|token|secret)"\s*:\s*"[^"]*"', re.IGNORECASE
)


def redact(text: str) -> str:
    for pattern in _PLAIN_SECRET_PATTERNS:
        text = pattern.sub(REDACTED, text)
    return _KEYED_SECRET.sub(lambda m: f'"{m.group(1)}": "{REDACTED}"', text)


class RedactingFilter(logging.Filter):
    """Rewrites the record's formatted message with secrets masked. Never
    raises and never drops a record: on any failure the record passes
    through unchanged rather than breaking logging."""

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            message = record.getMessage()
            redacted = redact(message)
            if redacted != message:
                record.msg = redacted
                record.args = None
        except Exception:  # noqa: BLE001
            pass
        return True


def _attach_filter(handler: logging.Handler) -> None:
    if not any(isinstance(f, RedactingFilter) for f in handler.filters):
        handler.addFilter(RedactingFilter())


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
    restrict_permissions(Path(handler.baseFilename))
    handler.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s")
    )
    _attach_filter(handler)
    # Console handlers (uvicorn's, or the root's) too: the filter lives on
    # handlers because logger-level filters don't apply to child loggers.
    for name in (None, "uvicorn", "uvicorn.error", "uvicorn.access"):
        for existing in logging.getLogger(name).handlers:
            _attach_filter(existing)
    logger = logging.getLogger("uvicorn.error")
    logger.addHandler(handler)
    logger.setLevel(level)
