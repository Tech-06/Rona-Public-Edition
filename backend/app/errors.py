"""Client-safe error text for unexpected failures.

An exception's `str()` can carry upstream URLs (with API keys in the query
string), file paths or SQL, so it must never reach an HTTP client. Callers
log the full traceback server-side under a short random id and hand the
client only that id, which an operator can grep for in the backend log.
"""

import logging
import uuid

import i18n

_LOGGER = logging.getLogger("uvicorn.error")


def new_error_id() -> str:
    return uuid.uuid4().hex[:8]


def log_exception(context: str, error_id: str) -> None:
    """Log the exception currently being handled (call from an `except`)."""
    _LOGGER.exception(i18n.t("errors.logged"), error_id, context)


def client_message(key: str, error_id: str, **kwargs: object) -> str:
    return i18n.t(key, error_id=error_id, **kwargs)
