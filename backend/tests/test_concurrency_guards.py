import asyncio
import sqlite3

import pytest

import create_db
from graph import threads
from subagents import runner
from subagents import store as subagent_store
from toolbox import db as toolbox_db
from toolbox.tools import subagent_tools


@pytest.fixture
def db_path(tmp_path, monkeypatch):
    path = tmp_path / "rona.db"
    sqlite3.connect(str(path)).close()
    monkeypatch.setattr(toolbox_db, "DB_PATH", path)
    monkeypatch.setattr(create_db, "DB_PATH", path)
    create_db.create_database()
    return path


async def test_subagent_limit_is_atomic(db_path, monkeypatch):
    monkeypatch.setattr(subagent_tools.settings, "subagent_max_concurrent", 1)
    spawned = []
    monkeypatch.setattr(runner, "spawn", lambda run_id, task, tier: spawned.append(run_id))

    results = await asyncio.gather(
        subagent_tools.start_subagent("a", "flash"),
        subagent_tools.start_subagent("b", "flash"),
        subagent_tools.start_subagent("c", "flash"),
    )

    assert sum(1 for r in results if r["success"]) == 1
    assert len(spawned) == 1
    assert subagent_store.count_running() == 1
    assert all("limit reached" in r["error"] for r in results if not r["success"])


def test_create_run_if_below_limit_respects_limit(db_path):
    assert subagent_store.create_run_if_below_limit("a", "t", "flash", 2)
    assert subagent_store.create_run_if_below_limit("b", "t", "flash", 2)
    assert not subagent_store.create_run_if_below_limit("c", "t", "flash", 2)
    subagent_store.complete_run("a", "s", "r")
    assert subagent_store.create_run_if_below_limit("c", "t", "flash", 2)


async def test_release_lock_removes_idle_entry():
    threads.get_lock("rel-1")
    threads.release_lock("rel-1")
    assert "rel-1" not in threads._locks


async def test_release_lock_keeps_held_lock():
    lock = threads.get_lock("rel-2")
    async with lock:
        threads.release_lock("rel-2")
        assert threads._locks.get("rel-2") is lock
    threads.release_lock("rel-2")
    assert "rel-2" not in threads._locks


async def test_repeated_release_for_random_ids_does_not_grow_locks():
    before = len(threads._locks)
    for i in range(50):
        threads.get_lock(f"rand-{i}")
        threads.release_lock(f"rand-{i}")
    assert len(threads._locks) == before
