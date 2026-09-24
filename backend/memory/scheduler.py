"""Background scheduler for automatic memory consolidation.

A single asyncio task, started from `app.main`'s lifespan, that wakes up
periodically and runs `memory.consolidation.run_once("schedule")`. The
next run time is derived from `memory.runs.last_finished_at()` (the last
recorded run, whoever triggered it) plus the configured interval rather
than kept as in-process state, so a manual "run now" pushes the automatic
schedule back and a dev-server reload doesn't cause an immediate re-run.

Settings changes require a restart to take effect here, consistent with
the rest of the app -- `start()` reads the interval once and the loop
keeps using that value for its lifetime.

Import rule: see memory/__init__.py -- sibling modules are imported and
referenced as module objects so tests can monkeypatch them by attribute.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta

import i18n
from memory import clock as memory_clock
from memory import consolidation as memory_consolidation
from memory import policy as memory_policy
from memory import runs as memory_runs

logger = logging.getLogger("uvicorn.error")

STARTUP_DELAY_SECONDS = 60
MAX_SLEEP_SECONDS = 3600
BUSY_RETRY_SECONDS = 60
ERROR_RETRY_SECONDS = 3600

_task: asyncio.Task | None = None
_interval_hours: int = 0


def next_due(
    last_finished: datetime | None, interval_hours: int, now: datetime
) -> datetime | None:
    """When the next automatic run is due, or None if automatic runs are
    off (`interval_hours <= 0`). A database with no recorded run yet is
    due immediately."""
    if interval_hours <= 0:
        return None
    if last_finished is None:
        return now
    return last_finished + timedelta(hours=interval_hours)


async def _loop() -> None:
    await asyncio.sleep(STARTUP_DELAY_SECONDS)
    while True:
        try:
            last = await asyncio.to_thread(memory_runs.last_finished_at)
            now = memory_clock.utc_now()
            due = next_due(last, _interval_hours, now)
            if due is None:
                return
            if due > now:
                await asyncio.sleep(min((due - now).total_seconds(), MAX_SLEEP_SECONDS))
                continue
            await asyncio.to_thread(memory_consolidation.run_once, "schedule")
        except asyncio.CancelledError:
            raise
        except memory_consolidation.ConsolidationBusy:
            await asyncio.sleep(BUSY_RETRY_SECONDS)
        except Exception as exc:  # noqa: BLE001
            logger.error(i18n.t("memory.log_scheduler_error"), exc)
            await asyncio.sleep(ERROR_RETRY_SECONDS)


def start() -> None:
    """Start the background task, from within the running event loop
    (called from app.main's lifespan). Does nothing if automatic
    consolidation is disabled (`consolidation_interval_hours <= 0`)."""
    global _task, _interval_hours
    _interval_hours = memory_policy.current_policy().consolidation_interval_hours
    if _interval_hours <= 0:
        logger.info(i18n.t("memory.log_scheduler_disabled"))
        return
    _task = asyncio.create_task(_loop())
    logger.info(i18n.t("memory.log_scheduler_started"), _interval_hours)


async def stop() -> None:
    """Cancel the background task (if any) and wait for it to unwind."""
    global _task, _interval_hours
    if _task is not None:
        _task.cancel()
        try:
            await _task
        except asyncio.CancelledError:
            pass
    _task = None
    _interval_hours = 0


def is_active() -> bool:
    return _task is not None and not _task.done()


def status() -> dict:
    active = is_active()
    next_run_at = None
    if active:
        due = next_due(memory_runs.last_finished_at(), _interval_hours, memory_clock.utc_now())
        if due is not None:
            next_run_at = memory_clock.to_db(due)
    return {"active": active, "interval_hours": _interval_hours, "next_run_at": next_run_at}
