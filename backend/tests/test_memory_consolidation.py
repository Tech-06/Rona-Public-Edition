"""Tests for memory/consolidation.py: promotion, archiving and deletion by
layer, dry runs, run bookkeeping and the busy lock.

Follows the same tmp_path + monkeypatch(toolbox.db.DB_PATH) pattern as
tests/test_memory_schema.py -- the real backend/rona.db is never touched.
`now` and `policy` are always passed explicitly so every scenario is
deterministic.
"""

import json
import sqlite3
from dataclasses import replace
from datetime import datetime, timedelta, timezone

import pytest

import create_db
from memory import archive, clock, consolidation, runs, schema
from memory.policy import MemoryPolicy
from toolbox import db as toolbox_db

NOW = datetime(2024, 6, 15, 12, 0, 0, tzinfo=timezone.utc)
DEFAULT_POLICY = MemoryPolicy()


@pytest.fixture(autouse=True)
def _clean_heal_cache():
    schema._reset_heal_cache()
    yield
    schema._reset_heal_cache()


@pytest.fixture
def db_paths(tmp_path, monkeypatch):
    db_path = tmp_path / "rona.db"
    monkeypatch.setattr(toolbox_db, "DB_PATH", db_path)
    monkeypatch.setattr(create_db, "DB_PATH", db_path)
    create_db.create_database()
    return db_path


def _connect(db_path) -> sqlite3.Connection:
    connection = sqlite3.connect(db_path)
    connection.row_factory = sqlite3.Row
    return connection


def _iso_days_ago(now: datetime, days: int) -> str:
    return clock.to_db(now - timedelta(days=days))


def _insert_memory(
    db_path,
    *,
    layer: str,
    content: str = "a memory",
    access_count: int = 0,
    created_at: str = "2024-01-01T00:00:00Z",
    last_accessed: str | None = None,
    layer_since: str | None = None,
    layer_hits: int = 0,
    person_id: int | None = None,
) -> int:
    embedding = json.dumps([0.1, 0.2, 0.3]).encode()
    connection = _connect(db_path)
    cursor = connection.execute(
        """
        INSERT INTO memories (
            person_id, layer, content, embedding, access_count, created_at,
            last_accessed, layer_since, layer_hits
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            person_id,
            layer,
            content,
            embedding,
            access_count,
            created_at,
            last_accessed,
            layer_since,
            layer_hits,
        ),
    )
    memory_id = cursor.lastrowid
    connection.commit()
    connection.close()
    return memory_id


def _get_memory(db_path, memory_id: int):
    connection = _connect(db_path)
    row = connection.execute("SELECT * FROM memories WHERE id = ?", (memory_id,)).fetchone()
    connection.close()
    return row


# ---- promotion thresholds --------------------------------------------------


def test_short_promotes_only_at_or_above_threshold(db_paths):
    below_id = _insert_memory(
        db_paths, layer="short", layer_hits=2, layer_since=clock.to_db(NOW)
    )
    at_id = _insert_memory(
        db_paths, layer="short", layer_hits=3, layer_since=clock.to_db(NOW)
    )

    consolidation.run_once("manual", now=NOW, policy=DEFAULT_POLICY)

    assert _get_memory(db_paths, below_id)["layer"] == "short"
    promoted = _get_memory(db_paths, at_id)
    assert promoted["layer"] == "seasonal"
    assert promoted["layer_hits"] == 0
    assert promoted["layer_since"] == clock.to_db(NOW)


def test_seasonal_promotes_only_at_or_above_threshold(db_paths):
    below_id = _insert_memory(
        db_paths, layer="seasonal", layer_hits=9, layer_since=clock.to_db(NOW)
    )
    at_id = _insert_memory(
        db_paths, layer="seasonal", layer_hits=10, layer_since=clock.to_db(NOW)
    )

    consolidation.run_once("manual", now=NOW, policy=DEFAULT_POLICY)

    assert _get_memory(db_paths, below_id)["layer"] == "seasonal"
    promoted = _get_memory(db_paths, at_id)
    assert promoted["layer"] == "deep"
    assert promoted["layer_hits"] == 0


def test_no_double_jump_a_hot_short_memory_only_reaches_seasonal(db_paths):
    memory_id = _insert_memory(
        db_paths, layer="short", layer_hits=50, layer_since=_iso_days_ago(NOW, 1)
    )

    consolidation.run_once("manual", now=NOW, policy=DEFAULT_POLICY)

    row = _get_memory(db_paths, memory_id)
    assert row["layer"] == "seasonal"
    assert row["layer_hits"] == 0
    assert row["layer_since"] == clock.to_db(NOW)


# ---- archive reference time -------------------------------------------------


def test_archive_uses_the_later_of_last_accessed_and_layer_since(db_paths):
    old = _iso_days_ago(NOW, 100)
    recent = _iso_days_ago(NOW, 1)
    very_old = _iso_days_ago(NOW, 200)

    stale_id = _insert_memory(db_paths, layer="seasonal", layer_since=old, last_accessed=old)
    recently_accessed_id = _insert_memory(
        db_paths, layer="seasonal", layer_since=old, last_accessed=recent
    )
    recently_promoted_id = _insert_memory(
        db_paths, layer="seasonal", layer_since=recent, last_accessed=very_old
    )

    report = consolidation.run_once("manual", now=NOW, policy=DEFAULT_POLICY)

    assert _get_memory(db_paths, stale_id) is None
    assert _get_memory(db_paths, recently_accessed_id)["layer"] == "seasonal"
    assert _get_memory(db_paths, recently_promoted_id)["layer"] == "seasonal"

    assert {item["id"] for item in report["archived"]} == {stale_id}

    matching = [row for row in archive.list_archive()["archive"] if row["memory_id"] == stale_id]
    assert len(matching) == 1
    assert matching[0]["reason"] == "auto"
    assert matching[0]["layer"] == "seasonal"


# ---- deletion ---------------------------------------------------------------


def test_delete_stale_short_memories_below_hit_threshold(db_paths):
    stale_id = _insert_memory(
        db_paths, layer="short", layer_since=_iso_days_ago(NOW, 8), layer_hits=2
    )
    fresh_id = _insert_memory(
        db_paths, layer="short", layer_since=_iso_days_ago(NOW, 6), layer_hits=2
    )

    consolidation.run_once("manual", now=NOW, policy=DEFAULT_POLICY)

    assert _get_memory(db_paths, stale_id) is None
    assert _get_memory(db_paths, fresh_id) is not None


def test_delete_skips_memories_at_or_above_the_hit_threshold(db_paths):
    memory_id = _insert_memory(
        db_paths, layer="short", layer_since=_iso_days_ago(NOW, 8), layer_hits=3
    )
    policy = replace(DEFAULT_POLICY, auto_promote_enabled=False)

    consolidation.run_once("manual", now=NOW, policy=policy)

    row = _get_memory(db_paths, memory_id)
    assert row is not None
    assert row["layer"] == "short"


# ---- deep is never touched ---------------------------------------------------


def test_deep_memories_are_never_touched(db_paths):
    memory_id = _insert_memory(
        db_paths,
        layer="deep",
        layer_hits=100,
        layer_since=_iso_days_ago(NOW, 1000),
        last_accessed=_iso_days_ago(NOW, 1000),
        created_at=_iso_days_ago(NOW, 1000),
    )

    consolidation.run_once("manual", now=NOW, policy=DEFAULT_POLICY)

    row = _get_memory(db_paths, memory_id)
    assert row["layer"] == "deep"
    assert row["layer_hits"] == 100


# ---- each toggle disables only its own step ---------------------------------


def test_auto_promote_disabled_skips_promotion(db_paths):
    memory_id = _insert_memory(
        db_paths, layer="short", layer_hits=10, layer_since=clock.to_db(NOW)
    )
    policy = replace(DEFAULT_POLICY, auto_promote_enabled=False)

    consolidation.run_once("manual", now=NOW, policy=policy)

    assert _get_memory(db_paths, memory_id)["layer"] == "short"


def test_auto_archive_disabled_skips_archiving(db_paths):
    memory_id = _insert_memory(
        db_paths,
        layer="seasonal",
        layer_since=_iso_days_ago(NOW, 200),
        last_accessed=_iso_days_ago(NOW, 200),
    )
    policy = replace(DEFAULT_POLICY, auto_archive_enabled=False)

    consolidation.run_once("manual", now=NOW, policy=policy)

    assert _get_memory(db_paths, memory_id) is not None


def test_auto_delete_disabled_skips_deletion(db_paths):
    memory_id = _insert_memory(
        db_paths, layer="short", layer_since=_iso_days_ago(NOW, 30), layer_hits=0
    )
    policy = replace(DEFAULT_POLICY, auto_delete_enabled=False)

    consolidation.run_once("manual", now=NOW, policy=policy)

    assert _get_memory(db_paths, memory_id) is not None


# ---- NULL layer_since normalization -----------------------------------------


def test_null_layer_since_is_normalized(db_paths):
    memory_id = _insert_memory(db_paths, layer="short", layer_since=None, layer_hits=0)

    consolidation.run_once("manual", now=NOW, policy=DEFAULT_POLICY)

    row = _get_memory(db_paths, memory_id)
    assert row["layer_since"] == clock.to_db(NOW)


# ---- dry run ------------------------------------------------------------------


def test_dry_run_changes_nothing_but_matches_the_following_real_run(db_paths):
    promote_id = _insert_memory(
        db_paths, layer="short", layer_hits=10, layer_since=clock.to_db(NOW)
    )
    archive_target_id = _insert_memory(
        db_paths,
        layer="seasonal",
        layer_since=_iso_days_ago(NOW, 200),
        last_accessed=_iso_days_ago(NOW, 200),
    )
    delete_id = _insert_memory(
        db_paths, layer="short", layer_since=_iso_days_ago(NOW, 30), layer_hits=0
    )

    dry_report = consolidation.run_once("manual", dry_run=True, now=NOW, policy=DEFAULT_POLICY)

    assert dry_report["dry_run"] is True
    assert dry_report["run_id"] is None
    assert runs.list_recent() == []
    assert _get_memory(db_paths, promote_id)["layer"] == "short"
    assert _get_memory(db_paths, archive_target_id) is not None
    assert _get_memory(db_paths, delete_id) is not None

    real_report = consolidation.run_once("manual", dry_run=False, now=NOW, policy=DEFAULT_POLICY)

    assert dry_report["counts"] == real_report["counts"]
    assert dry_report["promoted_short"] == real_report["promoted_short"]
    assert dry_report["archived"] == real_report["archived"]
    assert dry_report["deleted"] == real_report["deleted"]
    assert real_report["run_id"] is not None

    assert _get_memory(db_paths, promote_id)["layer"] == "seasonal"
    assert _get_memory(db_paths, archive_target_id) is None
    assert _get_memory(db_paths, delete_id) is None


# ---- run bookkeeping ----------------------------------------------------------


def test_real_run_records_a_run_row_with_counts(db_paths):
    _insert_memory(db_paths, layer="short", layer_hits=10, layer_since=clock.to_db(NOW))

    report = consolidation.run_once("manual", now=NOW, policy=DEFAULT_POLICY)

    last = runs.last_run()
    assert last is not None
    assert last["triggered_by"] == "manual"
    assert last["promoted_short"] == 1
    assert last["error"] is None
    assert report["run_id"] == last["id"]


def test_failed_run_records_error_row_and_reraises(db_paths, monkeypatch):
    _insert_memory(
        db_paths,
        layer="seasonal",
        layer_since=_iso_days_ago(NOW, 200),
        last_accessed=_iso_days_ago(NOW, 200),
    )

    def _boom(*_args, **_kwargs):
        raise RuntimeError("archive exploded")

    monkeypatch.setattr(archive, "archive_ids", _boom)

    with pytest.raises(RuntimeError, match="archive exploded"):
        consolidation.run_once("manual", now=NOW, policy=DEFAULT_POLICY)

    last = runs.last_run()
    assert last is not None
    assert last["error"] == "archive exploded"
    assert last["promoted_short"] == 0
    assert last["archived"] == 0


def test_run_once_raises_busy_when_lock_is_held(db_paths):
    with consolidation._run_lock, pytest.raises(consolidation.ConsolidationBusy):
        consolidation.run_once("manual", now=NOW, policy=DEFAULT_POLICY)


def test_runs_table_keeps_only_the_most_recent_fifty(db_paths):
    for _ in range(runs.KEEP_RUNS + 5):
        consolidation.run_once("manual", now=NOW, policy=DEFAULT_POLICY)

    assert len(runs.list_recent(limit=1000)) == runs.KEEP_RUNS
