"""Memory must degrade, not break, when the embedding model changes or no
key exists: model-tagged vectors, per-row skipping with a note, and a
keyword fallback. No network -- `_get_embedding` / the genai client are
mocked."""

import json
import sqlite3

import pytest

import create_db
from memory import schema as memory_schema
from toolbox import db as toolbox_db
from toolbox.tools import mem_tool


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    memory_schema._reset_heal_cache()
    monkeypatch.setattr(mem_tool, "_client", None)
    monkeypatch.setattr(mem_tool, "_client_key", None)
    yield
    memory_schema._reset_heal_cache()


@pytest.fixture
def db_path(tmp_path, monkeypatch):
    path = tmp_path / "rona.db"
    monkeypatch.setattr(toolbox_db, "DB_PATH", path)
    monkeypatch.setattr(create_db, "DB_PATH", path)
    create_db.create_database()
    return path


def _embed_with(monkeypatch, vectors, model="model-a"):
    monkeypatch.setenv("EMBEDDING_MODEL_NAME", model)
    monkeypatch.setattr(
        mem_tool, "_get_embedding", lambda text, task: vectors.get(text, [0.0, 0.0, 1.0])
    )


def _no_embedding(monkeypatch):
    def boom(text, task):
        raise RuntimeError("GOOGLE_API_KEY is not set.")

    monkeypatch.setattr(mem_tool, "_get_embedding", boom)


def _raw_insert(db_path, content, embedding, model):
    connection = sqlite3.connect(db_path)
    try:
        connection.execute(
            "INSERT INTO memories (layer, content, embedding, embedding_model) "
            "VALUES ('short', ?, ?, ?)",
            (content, embedding, model),
        )
        connection.commit()
    finally:
        connection.close()


def test_migration_5_adds_embedding_model_to_a_version_4_db(tmp_path, monkeypatch):
    path = tmp_path / "rona.db"
    monkeypatch.setattr(toolbox_db, "DB_PATH", path)
    monkeypatch.setattr(create_db, "DB_PATH", path)
    create_db.create_database()
    connection = sqlite3.connect(path)
    # Roll the version back: the guarded step must be idempotent when the
    # column already exists (e.g. self-healed at runtime).
    connection.execute("PRAGMA user_version = 4")
    connection.commit()
    connection.close()

    create_db.create_database()

    connection = sqlite3.connect(path)
    try:
        columns = {row[1] for row in connection.execute("PRAGMA table_info(memories)")}
        assert "embedding_model" in columns
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 7
    finally:
        connection.close()


def test_migration_5_adds_column_to_legacy_table(tmp_path, monkeypatch):
    path = tmp_path / "rona.db"
    monkeypatch.setattr(toolbox_db, "DB_PATH", path)
    monkeypatch.setattr(create_db, "DB_PATH", path)
    create_db.create_database()
    connection = sqlite3.connect(path)
    connection.execute("DROP TABLE memories")
    connection.execute(
        """
        CREATE TABLE memories (
            id INTEGER PRIMARY KEY AUTOINCREMENT, person_id INTEGER,
            layer TEXT NOT NULL, content TEXT NOT NULL, embedding BLOB NOT NULL,
            access_count INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
            last_accessed TEXT, layer_since TEXT,
            layer_hits INTEGER NOT NULL DEFAULT 0, metadata TEXT DEFAULT '{}'
        )
        """
    )
    connection.execute("PRAGMA user_version = 4")
    connection.commit()
    connection.close()

    create_db.create_database()

    connection = sqlite3.connect(path)
    try:
        columns = {row[1] for row in connection.execute("PRAGMA table_info(memories)")}
        assert "embedding_model" in columns
    finally:
        connection.close()


def test_add_memory_records_the_embedding_model(db_path, monkeypatch):
    _embed_with(monkeypatch, {}, model="model-a")
    result = mem_tool.add_memory("short", "hello")
    assert result["success"]
    connection = sqlite3.connect(db_path)
    try:
        row = connection.execute("SELECT embedding_model FROM memories").fetchone()
    finally:
        connection.close()
    assert row[0] == "model-a"


def test_search_skips_other_model_rows_and_adds_a_note(db_path, monkeypatch):
    _embed_with(monkeypatch, {"q": [1.0, 0.0, 0.0]}, model="model-b")
    _raw_insert(db_path, "same dim, other model", json.dumps([1.0, 0.0, 0.0]).encode(), "model-a")
    _raw_insert(db_path, "current", json.dumps([1.0, 0.0, 0.0]).encode(), "model-b")
    _raw_insert(db_path, "wrong dim", json.dumps([1.0, 0.0]).encode(), "model-b")

    result = mem_tool.search_memories_untracked("q")

    assert [r["content"] for r in result["results"]] == ["current"]
    assert result["skipped"]["other_model"] == 1
    assert result["skipped"]["dimension_mismatch"] == 1
    assert "re-embedding" in result["note"]


def test_search_compares_legacy_null_model_rows_when_dimensions_match(db_path, monkeypatch):
    _embed_with(monkeypatch, {"q": [1.0, 0.0, 0.0]}, model="model-b")
    _raw_insert(db_path, "legacy ok", json.dumps([1.0, 0.0, 0.0]).encode(), None)
    _raw_insert(db_path, "legacy wrong dim", json.dumps([1.0, 0.0]).encode(), None)

    result = mem_tool.search_memories_untracked("q")

    assert [r["content"] for r in result["results"]] == ["legacy ok"]
    assert result["skipped"]["dimension_mismatch"] == 1


def test_malformed_embedding_row_is_skipped_without_aborting(db_path, monkeypatch):
    _embed_with(monkeypatch, {"q": [1.0, 0.0, 0.0]})
    _raw_insert(db_path, "garbage", b"{not json", "model-a")
    _raw_insert(db_path, "not numbers", json.dumps(["a", "b", "c"]).encode(), "model-a")
    _raw_insert(db_path, "good", json.dumps([1.0, 0.0, 0.0]).encode(), "model-a")

    result = mem_tool.search_memories_untracked("q")

    assert result["success"]
    assert [r["content"] for r in result["results"]] == ["good"]
    assert result["skipped"]["malformed"] == 2


def test_add_memory_without_embedding_saves_with_empty_embedding(db_path, monkeypatch):
    _no_embedding(monkeypatch)

    result = mem_tool.add_memory("short", "Kahve severim")

    assert result["success"]
    assert result["embedded"] is False
    assert "without an embedding" in result["message"]
    connection = sqlite3.connect(db_path)
    try:
        row = connection.execute("SELECT embedding, embedding_model FROM memories").fetchone()
    finally:
        connection.close()
    assert not row[0]
    assert row[1] is None


def test_search_without_embedding_falls_back_to_keyword_mode(db_path, monkeypatch):
    _no_embedding(monkeypatch)
    older = mem_tool.add_memory("short", "likes coffee")["id"]
    both = mem_tool.add_memory("short", "Coffee with milk")["id"]
    mem_tool.add_memory("short", "unrelated")

    result = mem_tool.search_memories_untracked("COFFEE milk")

    assert result["success"]
    assert result["mode"] == "keyword"
    assert "Keyword mode" in result["note"]
    assert [r["id"] for r in result["results"]] == [both, older]


def test_client_is_rebuilt_when_the_api_key_changes(monkeypatch):
    built = []

    class FakeClient:
        def __init__(self, api_key):
            built.append(api_key)

    monkeypatch.setattr(mem_tool.genai, "Client", FakeClient)

    monkeypatch.setenv("GOOGLE_API_KEY", "key-one")
    first = mem_tool._get_client()
    assert mem_tool._get_client() is first
    monkeypatch.setenv("GOOGLE_API_KEY", "key-two")
    second = mem_tool._get_client()

    assert second is not first
    assert built == ["key-one", "key-two"]
