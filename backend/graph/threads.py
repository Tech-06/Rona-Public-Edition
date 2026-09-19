"""Per-conversation concurrency primitives and TTL purge orchestration.

Durable activity tracking (who was touched when, who is pinned) lives in
graph.conversations, backed by rona.db, so it survives restarts. This
module only keeps the process-local asyncio.Lock per thread_id -- locks
cannot be persisted or shared across processes anyway -- plus the purge
loop that ties the two together.
"""

import logging
import time
from asyncio import Lock

import i18n
from graph import conversations

logger = logging.getLogger("uvicorn.error")

_locks: dict[str, Lock] = {}

PURGE_INTERVAL_SECONDS = 60.0
PURGE_BATCH_LIMIT = 50

_last_purge_monotonic = 0.0


def get_lock(thread_id: str) -> Lock:
    lock = _locks.get(thread_id)
    if lock is None:
        lock = Lock()
        _locks[thread_id] = lock
    return lock


def is_locked(thread_id: str) -> bool:
    lock = _locks.get(thread_id)
    return lock is not None and lock.locked()


async def purge_expired(ttl_seconds: int, checkpointer, *, force: bool = False) -> int:
    """Delete idle, unpinned conversations past ttl_seconds.

    Called from the pre-amble of every chat turn under app/main.py's
    global store_lock, which serializes ALL conversations' turns -- so
    this must stay cheap. `ttl_seconds <= 0` (the new default) returns
    immediately at zero cost, before the throttle check even runs.
    Otherwise it's throttled to once per PURGE_INTERVAL_SECONDS and capped
    at PURGE_BATCH_LIMIT deletions per pass, so a backlog built up during
    downtime drains gradually across turns instead of stalling the first
    turn after a long idle period.

    Returns the number of conversations purged (mainly for tests/logging).
    """
    global _last_purge_monotonic
    if ttl_seconds <= 0 or checkpointer is None:
        return 0
    now = time.monotonic()
    if not force and now - _last_purge_monotonic < PURGE_INTERVAL_SECONDS:
        return 0
    _last_purge_monotonic = now

    delete = getattr(checkpointer, "adelete_thread", None)
    if delete is None:
        return 0

    purged = 0
    candidates = conversations.expired_candidates(ttl_seconds, limit=PURGE_BATCH_LIMIT)
    for thread_id in candidates:
        if is_locked(thread_id):
            continue
        try:
            await delete(thread_id)
        except NotImplementedError:
            break
        except Exception:
            logger.exception(i18n.t("graph.log_purge_failed"), thread_id)
            continue
        conversations.mark_purged(thread_id)
        _locks.pop(thread_id, None)
        purged += 1
    return purged
