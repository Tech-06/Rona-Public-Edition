import sqlite3
from datetime import datetime, timedelta, timezone

import pytest

from graph import conversations
from toolbox import db as toolbox_db


def _backdate(db_path, thread_id: str, seconds_ago: float) -> None:
    """Directly rewrite a row's last_active to simulate idle time passing,
    bypassing conversations.touch() (which always stamps "now")."""
    timestamp = (
        datetime.now(timezone.utc) - timedelta(seconds=seconds_ago)
    ).strftime("%Y-%m-%dT%H:%M:%SZ")
    connection = sqlite3.connect(str(db_path))
    connection.execute(
        "UPDATE conversation_registry SET last_active = ? WHERE thread_id = ?",
        (timestamp, thread_id),
    )
    connection.commit()
    connection.close()


def _backdate_purge(db_path, thread_id: str, days_ago: float) -> None:
    """Directly rewrite a row's purged_at to simulate an old tombstone."""
    timestamp = (
        datetime.now(timezone.utc) - timedelta(days=days_ago)
    ).strftime("%Y-%m-%dT%H:%M:%SZ")
    connection = sqlite3.connect(str(db_path))
    connection.execute(
        "UPDATE conversation_registry SET purged_at = ? WHERE thread_id = ?",
        (timestamp, thread_id),
    )
    connection.commit()
    connection.close()


@pytest.fixture
def db_path(tmp_path, monkeypatch):
    path = tmp_path / "rona.db"
    # toolbox.db.connect()/connect_if_exists() both require the file to
    # already exist (matching how create_db.py, not toolbox.db, is the
    # thing that actually creates rona.db in production) -- so create an
    # empty file first, the same way create_db.py's own sqlite3.connect()
    # call does.
    sqlite3.connect(str(path)).close()
    monkeypatch.setattr(toolbox_db, "DB_PATH", path)
    conversations.ensure_schema()
    return path


def test_ensure_schema_is_idempotent(db_path):
    conversations.ensure_schema()
    conversations.ensure_schema()
    connection = sqlite3.connect(str(db_path))
    tables = {
        row[0]
        for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
    }
    connection.close()
    assert "conversation_registry" in tables


def test_touch_upserts_and_clears_tombstone(db_path):
    conversations.touch("conv-1")
    row = conversations.get("conv-1")
    assert row is not None
    assert row["pinned"] is False
    assert row["purged_at"] is None

    conversations.mark_purged("conv-1")
    assert conversations.get("conv-1")["purged_at"] is not None

    conversations.touch("conv-1")
    assert conversations.get("conv-1")["purged_at"] is None


def test_pin_preserves_last_active_unpin_refreshes_it(db_path):
    conversations.touch("conv-1")
    _backdate(db_path, "conv-1", seconds_ago=10_000)
    backdated = conversations.get("conv-1")["last_active"]

    pinned_row = conversations.set_pinned("conv-1", True)
    assert pinned_row["pinned"] is True
    assert pinned_row["last_active"] == backdated  # unchanged by pinning

    unpinned_row = conversations.set_pinned("conv-1", False)
    assert unpinned_row["pinned"] is False
    assert unpinned_row["last_active"] != backdated  # refreshed by unpinning


def test_set_pinned_upserts_unknown_thread(db_path):
    assert conversations.get("never-seen") is None
    row = conversations.set_pinned("never-seen", True)
    assert row["pinned"] is True
    assert conversations.get("never-seen") is not None


def test_expired_candidates_skips_pinned_and_tombstoned(db_path):
    conversations.touch("old-unpinned")
    _backdate(db_path, "old-unpinned", seconds_ago=1000)

    conversations.touch("old-pinned")
    _backdate(db_path, "old-pinned", seconds_ago=1000)
    conversations.set_pinned("old-pinned", True)
    _backdate(db_path, "old-pinned", seconds_ago=1000)  # re-backdate post-pin

    conversations.touch("old-purged")
    _backdate(db_path, "old-purged", seconds_ago=1000)
    conversations.mark_purged("old-purged")

    conversations.touch("fresh-unpinned")

    candidates = conversations.expired_candidates(ttl_seconds=60)
    assert candidates == ["old-unpinned"]


def test_expired_candidates_disabled_when_ttl_not_positive(db_path):
    conversations.touch("old-unpinned")
    _backdate(db_path, "old-unpinned", seconds_ago=1000)
    assert conversations.expired_candidates(ttl_seconds=0) == []
    assert conversations.expired_candidates(ttl_seconds=-1) == []


def test_expired_candidates_respects_limit_oldest_first(db_path):
    for index, seconds_ago in enumerate([300, 200, 100]):
        thread_id = f"conv-{index}"
        conversations.touch(thread_id)
        _backdate(db_path, thread_id, seconds_ago=seconds_ago)

    candidates = conversations.expired_candidates(ttl_seconds=10, limit=2)
    assert candidates == ["conv-0", "conv-1"]  # oldest (largest idle) first


def test_reconcile_inserts_unknown_and_preserves_pinned_orphans(db_path):
    conversations.touch("known-active")

    conversations.set_pinned("pinned-orphan", True)  # never had a real turn

    conversations.touch("stale-unpinned")  # its checkpoints are "gone"

    inserted, marked_purged = conversations.reconcile(
        known_thread_ids=["known-active", "brand-new-from-checkpoints"]
    )

    assert inserted == 1
    assert marked_purged == 1

    assert conversations.get("brand-new-from-checkpoints") is not None
    assert conversations.get("known-active")["purged_at"] is None

    pinned_orphan = conversations.get("pinned-orphan")
    assert pinned_orphan["pinned"] is True
    assert pinned_orphan["purged_at"] is None  # never pruned while pinned

    assert conversations.get("stale-unpinned")["purged_at"] is not None


def test_sweep_tombstones_removes_only_old_ones(db_path):
    conversations.touch("old-tombstone")
    conversations.mark_purged("old-tombstone")
    _backdate_purge(db_path, "old-tombstone", days_ago=40)

    conversations.touch("recent-tombstone")
    conversations.mark_purged("recent-tombstone")

    deleted = conversations.sweep_tombstones(max_age_days=30)

    assert deleted == 1
    assert conversations.get("old-tombstone") is None
    assert conversations.get("recent-tombstone") is not None


def test_list_purged_respects_retention_window(db_path):
    conversations.touch("old-tombstone")
    conversations.mark_purged("old-tombstone")
    _backdate_purge(db_path, "old-tombstone", days_ago=40)

    conversations.touch("recent-tombstone")
    conversations.mark_purged("recent-tombstone")

    purged = conversations.list_purged(max_age_days=30)

    assert purged == ["recent-tombstone"]


def test_forget_hard_deletes(db_path):
    conversations.touch("conv-1")
    conversations.forget("conv-1")
    assert conversations.get("conv-1") is None


def test_count_excludes_purged(db_path):
    conversations.touch("conv-1")
    conversations.touch("conv-2")
    conversations.mark_purged("conv-2")
    assert conversations.count() == 1


def test_functions_degrade_to_noop_without_db(tmp_path, monkeypatch):
    monkeypatch.setattr(toolbox_db, "DB_PATH", tmp_path / "does-not-exist.db")
    conversations.ensure_schema()  # must not raise
    conversations.touch("conv-1")  # must not raise
    assert conversations.get("conv-1") is None
    assert conversations.list_active() == []
    assert conversations.list_purged() == []
    assert conversations.count() == 0
    assert conversations.expired_candidates(60) == []
    assert conversations.reconcile(["conv-1"]) == (0, 0)
