import asyncio
import time

_activity: dict[str, float] = {}
_locks: dict[str, asyncio.Lock] = {}


def touch(thread_id: str) -> None:
    _activity[thread_id] = time.time()


def get_lock(thread_id: str) -> asyncio.Lock:
    lock = _locks.get(thread_id)
    if lock is None:
        lock = asyncio.Lock()
        _locks[thread_id] = lock
    return lock


def active_count() -> int:
    return len(_activity)


def snapshot_activity() -> dict[str, float]:
    return dict(_activity)


def _is_locked(thread_id: str) -> bool:
    lock = _locks.get(thread_id)
    return lock is not None and lock.locked()


async def purge_expired(ttl_seconds: int, checkpointer) -> None:
    if ttl_seconds <= 0 or checkpointer is None:
        return
    now = time.time()
    expired = [
        thread_id
        for thread_id, last_active in _activity.items()
        if now - last_active > ttl_seconds and not _is_locked(thread_id)
    ]
    for thread_id in expired:
        del _activity[thread_id]
        lock = _locks.get(thread_id)
        if lock is not None and not lock.locked():
            del _locks[thread_id]
        delete = getattr(checkpointer, "adelete_thread", None)
        if delete is None:
            continue
        try:
            await delete(thread_id)
        except NotImplementedError:
            continue
