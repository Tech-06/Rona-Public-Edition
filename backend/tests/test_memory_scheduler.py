"""Tests for memory/scheduler.py: due-time math and the background task's
start/stop lifecycle.

Async tests run under pytest-asyncio's `asyncio_mode = "auto"` (configured
in pyproject.toml). Nothing here touches a real database -- `memory.runs`
and `memory.consolidation` are monkeypatched at the module-attribute level
so scheduler.py's own module-object references
(`memory_runs.last_finished_at`, `memory_consolidation.run_once`) pick up
the fakes.
"""

import asyncio
from datetime import datetime, timedelta, timezone

import pytest

from memory import clock, consolidation, runs, scheduler
from memory import policy as policy_module

NOW = datetime(2024, 1, 1, tzinfo=timezone.utc)


@pytest.fixture(autouse=True)
def _reset_scheduler_state():
    yield
    scheduler._task = None
    scheduler._interval_hours = 0


# ---- next_due -----------------------------------------------------------------


def test_next_due_is_none_when_interval_is_zero_or_negative():
    assert scheduler.next_due(None, 0, NOW) is None
    assert scheduler.next_due(NOW, -1, NOW) is None


def test_next_due_is_now_with_no_previous_run():
    assert scheduler.next_due(None, 24, NOW) == NOW


def test_next_due_adds_the_interval_to_the_last_finished_run():
    later = NOW + timedelta(hours=5)
    assert scheduler.next_due(NOW, 24, later) == NOW + timedelta(hours=24)


# ---- start() / interval 0 ------------------------------------------------------


def test_start_creates_no_task_when_the_interval_is_zero(monkeypatch):
    monkeypatch.setattr(
        policy_module,
        "current_policy",
        lambda: policy_module.MemoryPolicy(consolidation_interval_hours=0),
    )

    scheduler.start()

    assert scheduler._task is None
    assert scheduler.is_active() is False


def test_status_reports_inactive_by_default():
    assert scheduler.status() == {"active": False, "interval_hours": 0, "next_run_at": None}


# ---- the running loop -----------------------------------------------------------


async def _wait_until(predicate, *, attempts: int = 200, delay: float = 0.01) -> None:
    for _ in range(attempts):
        if predicate():
            return
        await asyncio.sleep(delay)
    raise AssertionError("condition was not met in time")


async def test_loop_runs_exactly_once_then_stops_cleanly(monkeypatch):
    monkeypatch.setattr(scheduler, "STARTUP_DELAY_SECONDS", 0)
    monkeypatch.setattr(
        policy_module,
        "current_policy",
        lambda: policy_module.MemoryPolicy(consolidation_interval_hours=24),
    )
    monkeypatch.setattr(clock, "utc_now", lambda: NOW)

    calls = {"last_finished": 0, "run_once": 0}

    def fake_last_finished_at():
        calls["last_finished"] += 1
        return None if calls["last_finished"] == 1 else NOW

    def fake_run_once(triggered_by):
        assert triggered_by == "schedule"
        calls["run_once"] += 1

    monkeypatch.setattr(runs, "last_finished_at", fake_last_finished_at)
    monkeypatch.setattr(consolidation, "run_once", fake_run_once)

    scheduler.start()
    assert scheduler.is_active() is True

    await _wait_until(lambda: calls["run_once"] >= 1)
    await scheduler.stop()

    assert calls["run_once"] == 1
    assert scheduler.is_active() is False


async def test_loop_retries_after_busy_without_crashing(monkeypatch):
    monkeypatch.setattr(scheduler, "STARTUP_DELAY_SECONDS", 0)
    monkeypatch.setattr(scheduler, "BUSY_RETRY_SECONDS", 0)
    monkeypatch.setattr(
        policy_module,
        "current_policy",
        lambda: policy_module.MemoryPolicy(consolidation_interval_hours=24),
    )
    monkeypatch.setattr(clock, "utc_now", lambda: NOW)
    monkeypatch.setattr(runs, "last_finished_at", lambda: None)

    calls = {"count": 0}

    def fake_run_once(triggered_by):
        calls["count"] += 1
        raise consolidation.ConsolidationBusy("busy")

    monkeypatch.setattr(consolidation, "run_once", fake_run_once)

    scheduler.start()
    await _wait_until(lambda: calls["count"] >= 2)
    await scheduler.stop()

    assert calls["count"] >= 2


async def test_loop_retries_after_a_generic_error_without_crashing(monkeypatch):
    monkeypatch.setattr(scheduler, "STARTUP_DELAY_SECONDS", 0)
    monkeypatch.setattr(scheduler, "ERROR_RETRY_SECONDS", 0)
    monkeypatch.setattr(
        policy_module,
        "current_policy",
        lambda: policy_module.MemoryPolicy(consolidation_interval_hours=24),
    )
    monkeypatch.setattr(clock, "utc_now", lambda: NOW)
    monkeypatch.setattr(runs, "last_finished_at", lambda: None)

    calls = {"count": 0}

    def fake_run_once(triggered_by):
        calls["count"] += 1
        raise RuntimeError("boom")

    monkeypatch.setattr(consolidation, "run_once", fake_run_once)

    scheduler.start()
    await _wait_until(lambda: calls["count"] >= 2)
    await scheduler.stop()

    assert calls["count"] >= 2
