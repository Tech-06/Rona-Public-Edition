"""Tests for memory/schema.py's DDL, self-healing migration and
memory/clock.py + memory/policy.py, which schema.py and create_db.py
build on.

Follows the same tmp_path + monkeypatch(toolbox.db.DB_PATH) pattern as
tests/test_dashboard_memory.py -- the real backend/rona.db is never
touched.
"""

import sqlite3
from dataclasses import fields as dc_fields
from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

import create_db
from app.config import Settings
from memory import clock, policy, schema
from toolbox import db as toolbox_db

_REQUIRED_SETTINGS_FIELDS = {
    "auth_token": "test-token",
    "flash_model": "test-model",
    "flash_model_url": "http://example.com",
    "flash_model_api": "test-key",
}


def _settings(**overrides) -> Settings:
    return Settings(_env_file=None, **{**_REQUIRED_SETTINGS_FIELDS, **overrides})


# The pre-consolidation `CREATE TABLE memories` statement, used to simulate an
# old database that predates layer_since/layer_hits.
_LEGACY_MEMORIES_SQL = """
CREATE TABLE memories (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    person_id INTEGER,
    layer TEXT NOT NULL CHECK(layer IN ('deep', 'seasonal', 'short')),
    content TEXT NOT NULL,
    embedding BLOB NOT NULL,
    access_count INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    last_accessed TEXT,
    metadata TEXT DEFAULT '{}'
)
"""


@pytest.fixture(autouse=True)
def _clean_heal_cache():
    """memory.schema.connect()/connect_if_exists() cache which db paths
    they've already repaired -- reset it around every test so tmp_path
    reuse across the test run (unlikely, but possible) can't leak."""
    schema._reset_heal_cache()
    yield
    schema._reset_heal_cache()


@pytest.fixture
def db_paths(tmp_path, monkeypatch):
    db_path = tmp_path / "rona.db"
    monkeypatch.setattr(toolbox_db, "DB_PATH", db_path)
    monkeypatch.setattr(create_db, "DB_PATH", db_path)
    return db_path


def _table_names(connection) -> set[str]:
    return {
        row[0]
        for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")
    }


def _index_names(connection) -> set[str]:
    return {
        row[0]
        for row in connection.execute("SELECT name FROM sqlite_master WHERE type='index'")
    }


def _memories_columns(connection) -> set[str]:
    return {row[1] for row in connection.execute("PRAGMA table_info(memories)")}


# ---- create_db.py on a fresh database -----------------------------------


def test_create_database_fresh_db_has_full_memory_schema(db_paths):
    create_db.create_database()

    connection = sqlite3.connect(db_paths)
    try:
        assert {"layer_since", "layer_hits"} <= _memories_columns(connection)
        assert {"memory_archive", "memory_consolidation_runs"} <= _table_names(connection)
        assert "idx_memories_layer" in _index_names(connection)
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 3
    finally:
        connection.close()


def test_create_database_upgrades_legacy_db_at_user_version_1(db_paths):
    connection = sqlite3.connect(db_paths)
    connection.execute(_LEGACY_MEMORIES_SQL)
    connection.execute("PRAGMA user_version = 1")
    connection.commit()
    connection.close()

    create_db.create_database()

    connection = sqlite3.connect(db_paths)
    try:
        assert {"layer_since", "layer_hits"} <= _memories_columns(connection)
        assert {"memory_archive", "memory_consolidation_runs"} <= _table_names(connection)
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 3
    finally:
        connection.close()


# ---- apply_schema() directly, against a hand-built legacy table --------


def test_apply_schema_migrates_legacy_table_and_backfills_layer_since(tmp_path):
    connection = sqlite3.connect(tmp_path / "legacy.db")
    connection.execute(_LEGACY_MEMORIES_SQL)
    connection.execute(
        "INSERT INTO memories (layer, content, embedding, access_count, created_at) "
        "VALUES ('short', 'old short memory', ?, 7, '2020-01-01T00:00:00Z')",
        (b"[]",),
    )
    connection.execute(
        "INSERT INTO memories (layer, content, embedding, access_count, created_at) "
        "VALUES ('deep', 'old deep memory', ?, 7, '2020-06-01T00:00:00Z')",
        (b"[]",),
    )
    connection.commit()

    fixed_now = datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
    added = schema.apply_schema(connection, now=fixed_now)
    assert added == ["layer_since", "layer_hits"]

    rows = connection.execute(
        "SELECT layer_since, layer_hits, access_count FROM memories ORDER BY id"
    ).fetchall()
    assert len(rows) == 2
    for layer_since, layer_hits, access_count in rows:
        assert layer_since == clock.to_db(fixed_now)
        assert layer_hits == 0
        assert access_count == 7  # untouched -- old access_count is not migrated

    # Idempotent: nothing left to add, nothing changes.
    second = schema.apply_schema(
        connection, now=datetime(2030, 1, 1, tzinfo=timezone.utc)
    )
    assert second == []
    unchanged = connection.execute(
        "SELECT layer_since, layer_hits FROM memories ORDER BY id"
    ).fetchall()
    assert unchanged == [(clock.to_db(fixed_now), 0), (clock.to_db(fixed_now), 0)]

    connection.close()


# ---- ensure_schema() -----------------------------------------------------


def test_ensure_schema_does_not_create_a_missing_db_file(tmp_path, monkeypatch):
    db_path = tmp_path / "does-not-exist.db"
    monkeypatch.setattr(toolbox_db, "DB_PATH", db_path)

    schema.ensure_schema()

    assert not db_path.exists()


def test_ensure_schema_upgrades_an_existing_db(tmp_path, monkeypatch):
    db_path = tmp_path / "rona.db"
    connection = sqlite3.connect(db_path)
    connection.execute(_LEGACY_MEMORIES_SQL)
    connection.commit()
    connection.close()

    monkeypatch.setattr(toolbox_db, "DB_PATH", db_path)

    schema.ensure_schema()

    connection = sqlite3.connect(db_path)
    try:
        assert {"layer_since", "layer_hits"} <= _memories_columns(connection)
    finally:
        connection.close()


# ---- connect() / connect_if_exists() self-heal --------------------------


def test_connect_repairs_a_legacy_database(tmp_path, monkeypatch):
    db_path = tmp_path / "legacy.db"
    connection = sqlite3.connect(db_path)
    connection.execute(_LEGACY_MEMORIES_SQL)
    connection.commit()
    connection.close()

    monkeypatch.setattr(toolbox_db, "DB_PATH", db_path)

    healed = schema.connect()
    try:
        assert {"layer_since", "layer_hits"} <= _memories_columns(healed)
    finally:
        healed.close()


def test_connect_if_exists_returns_none_for_missing_db(tmp_path, monkeypatch):
    db_path = tmp_path / "does-not-exist.db"
    monkeypatch.setattr(toolbox_db, "DB_PATH", db_path)

    assert schema.connect_if_exists() is None


# ---- immediate_transaction() ---------------------------------------------


def test_immediate_transaction_commits_on_success():
    connection = sqlite3.connect(":memory:")
    connection.execute("CREATE TABLE t (x INTEGER)")
    with schema.immediate_transaction(connection):
        connection.execute("INSERT INTO t VALUES (1)")
    assert connection.execute("SELECT x FROM t").fetchall() == [(1,)]
    connection.close()


def test_immediate_transaction_rolls_back_on_exception():
    connection = sqlite3.connect(":memory:")
    connection.execute("CREATE TABLE t (x INTEGER)")
    with pytest.raises(RuntimeError), schema.immediate_transaction(connection):
        connection.execute("INSERT INTO t VALUES (1)")
        raise RuntimeError("boom")
    assert connection.execute("SELECT x FROM t").fetchall() == []
    connection.close()


# ---- memory/clock.py ------------------------------------------------------


def test_clock_round_trip_and_naive_is_treated_as_utc():
    aware = datetime(2024, 5, 1, 10, 30, 0, tzinfo=timezone.utc)
    text = clock.to_db(aware)
    assert text == "2024-05-01T10:30:00Z"
    assert clock.from_db(text) == aware

    naive = datetime(2024, 5, 1, 10, 30, 0)  # noqa: DTZ001 -- deliberately tz-naive
    assert clock.to_db(naive) == text


def test_clock_from_db_handles_missing_and_malformed_input():
    assert clock.from_db(None) is None
    assert clock.from_db("") is None
    assert clock.from_db("not-a-timestamp") is None


# ---- memory/policy.py -----------------------------------------------------


def test_memory_policy_fields_match_settings_defaults():
    default_policy = policy.MemoryPolicy()
    for field in dc_fields(policy.MemoryPolicy):
        settings_name = f"memory_{field.name}"
        assert settings_name in Settings.model_fields
        assert Settings.model_fields[settings_name].default == getattr(
            default_policy, field.name
        )


def test_memory_policy_from_settings_maps_values():
    settings = _settings(
        memory_short_promote_hits=5,
        memory_auto_delete_enabled=False,
        memory_consolidation_interval_hours=0,
    )
    derived = policy.MemoryPolicy.from_settings(settings)
    assert derived.short_promote_hits == 5
    assert derived.auto_delete_enabled is False
    assert derived.consolidation_interval_hours == 0
    assert derived.seasonal_promote_hits == 10  # untouched, stays default


def test_memory_policy_as_dict_round_trips_all_fields():
    default_policy = policy.MemoryPolicy()
    as_dict = default_policy.as_dict()
    assert set(as_dict) == {field.name for field in dc_fields(policy.MemoryPolicy)}
    assert policy.MemoryPolicy(**as_dict) == default_policy


# ---- Settings validation for the new memory_* fields ----------------------


def test_settings_rejects_short_promote_hits_zero():
    with pytest.raises(ValidationError):
        _settings(memory_short_promote_hits=0)


def test_settings_accepts_zero_interval_and_cooldown():
    settings = _settings(
        memory_consolidation_interval_hours=0, memory_access_cooldown_hours=0
    )
    assert settings.memory_consolidation_interval_hours == 0
    assert settings.memory_access_cooldown_hours == 0
