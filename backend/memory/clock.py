"""UTC time helpers shared by every `memory.*` module.

`memories.created_at` (and every timestamp this package adds:
`layer_since`, `archived_at`, run start/finish times, ...) is stored as
the same fixed-width UTC string SQLite already used for it:
`'%Y-%m-%dT%H:%M:%SZ'`. That format sorts identically whether compared
as a string or parsed into a datetime, which is what lets consolidation
queries use plain `<`/`>=` string comparisons instead of a SQLite date
function.

Stdlib only -- see memory/__init__.py's import rule.
"""

from __future__ import annotations

from datetime import datetime, timezone

DB_TIME_FORMAT = "%Y-%m-%dT%H:%M:%SZ"


def utc_now() -> datetime:
    """The current time, timezone-aware UTC, truncated to whole seconds
    (matching the precision `DB_TIME_FORMAT` actually stores)."""
    return datetime.now(timezone.utc).replace(microsecond=0)


def to_db(dt: datetime) -> str:
    """Format `dt` the way it's stored in the database.

    A naive datetime is treated as already being UTC (rather than raising
    or guessing the local zone) so callers that build a `datetime` by hand
    in tests don't have to remember to attach a tzinfo.
    """
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    return dt.strftime(DB_TIME_FORMAT)


def from_db(text: str | None) -> datetime | None:
    """Parse a stored timestamp back into an aware UTC datetime.

    Returns None for a missing value (None or empty string) and for any
    string that doesn't match `DB_TIME_FORMAT`, rather than raising --
    callers treat "unparseable" the same as "not set".
    """
    if not text:
        return None
    try:
        return datetime.strptime(text, DB_TIME_FORMAT).replace(tzinfo=timezone.utc)
    except ValueError:
        return None
