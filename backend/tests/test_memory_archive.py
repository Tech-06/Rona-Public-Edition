"""Tests for memory/archive.py: manual archiving, restore, listing and
person-linked bulk archiving.

Follows the same tmp_path + monkeypatch(toolbox.db.DB_PATH) pattern as
tests/test_memory_schema.py -- the real backend/rona.db is never touched.
"""

import json
import sqlite3
from datetime import datetime, timezone

import pytest

import create_db
from memory import archive, clock, schema
from toolbox import db as toolbox_db

NOW = datetime(2024, 6, 15, 12, 0, 0, tzinfo=timezone.utc)


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


def _insert_person(db_path, name: str = "Ada") -> int:
    connection = _connect(db_path)
    cursor = connection.execute("INSERT INTO people (name) VALUES (?)", (name,))
    connection.commit()
    person_id = cursor.lastrowid
    connection.close()
    return person_id


def _insert_memory(
    db_path,
    *,
    layer: str = "deep",
    content: str = "a memory",
    access_count: int = 3,
    created_at: str = "2024-01-01T00:00:00Z",
    last_accessed: str | None = "2024-02-01T00:00:00Z",
    layer_since: str | None = "2024-01-01T00:00:00Z",
    layer_hits: int = 1,
    person_id: int | None = None,
    metadata: str = '{"k": "v"}',
) -> int:
    embedding = json.dumps([0.1, 0.2, 0.3]).encode()
    connection = _connect(db_path)
    cursor = connection.execute(
        """
        INSERT INTO memories (
            person_id, layer, content, embedding, access_count, created_at,
            last_accessed, layer_since, layer_hits, metadata
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
            metadata,
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


def _get_archive_row(db_path, archive_id: int):
    connection = _connect(db_path)
    row = connection.execute(
        "SELECT * FROM memory_archive WHERE id = ?", (archive_id,)
    ).fetchone()
    connection.close()
    return row


# ---- archive_memory -----------------------------------------------------------


def test_archive_memory_copies_all_fields_and_removes_the_memory(db_paths):
    memory_id = _insert_memory(
        db_paths,
        layer="seasonal",
        content="loves tea",
        access_count=5,
        created_at="2024-01-01T00:00:00Z",
        last_accessed="2024-02-01T00:00:00Z",
        layer_since="2024-01-15T00:00:00Z",
        layer_hits=2,
        metadata='{"source": "chat"}',
    )

    archive_id = archive.archive_memory(memory_id, reason="manual")

    assert _get_memory(db_paths, memory_id) is None
    row = _get_archive_row(db_paths, archive_id)
    assert row["memory_id"] == memory_id
    assert row["layer"] == "seasonal"
    assert row["content"] == "loves tea"
    assert row["access_count"] == 5
    assert row["created_at"] == "2024-01-01T00:00:00Z"
    assert row["last_accessed"] == "2024-02-01T00:00:00Z"
    assert json.loads(row["metadata"]) == {"source": "chat"}
    assert row["reason"] == "manual"
    assert row["archived_at"]


def test_archive_memory_rejects_an_invalid_reason(db_paths):
    memory_id = _insert_memory(db_paths)
    with pytest.raises(ValueError):
        archive.archive_memory(memory_id, reason="not-a-reason")
    assert _get_memory(db_paths, memory_id) is not None  # untouched


def test_archive_memory_missing_id_raises_not_found(db_paths):
    with pytest.raises(archive.NotFound):
        archive.archive_memory(999, reason="manual")


def test_archive_ids_validates_reason(db_paths):
    connection = _connect(db_paths)
    with pytest.raises(ValueError):
        archive.archive_ids(connection.cursor(), [1], reason="bogus", now=clock.to_db(NOW))
    connection.close()


def test_archive_ids_skips_ids_that_no_longer_exist(db_paths):
    memory_id = _insert_memory(db_paths, content="still here")
    connection = _connect(db_paths)
    archived = archive.archive_ids(
        connection.cursor(), [memory_id, 999999], reason="auto", now=clock.to_db(NOW)
    )
    connection.commit()
    connection.close()

    assert archived == 1
    assert _get_memory(db_paths, memory_id) is None


# ---- restore --------------------------------------------------------------------


def test_restore_missing_archive_id_raises_not_found(db_paths):
    with pytest.raises(archive.NotFound):
        archive.restore(999)


def test_restore_reinstates_as_deep_with_a_fresh_layer_clock_and_reuses_the_id(
    db_paths, monkeypatch
):
    memory_id = _insert_memory(
        db_paths, layer="short", content="temp note", access_count=4, layer_hits=7
    )
    archive_id = archive.archive_memory(memory_id, reason="manual")

    fixed_now = datetime(2024, 7, 1, tzinfo=timezone.utc)
    monkeypatch.setattr(clock, "utc_now", lambda: fixed_now)

    restored_id = archive.restore(archive_id)

    assert restored_id == memory_id
    row = _get_memory(db_paths, memory_id)
    assert row["layer"] == "deep"
    assert row["layer_hits"] == 0
    assert row["layer_since"] == clock.to_db(fixed_now)
    assert row["content"] == "temp note"
    assert row["access_count"] == 4
    assert _get_archive_row(db_paths, archive_id) is None


def test_restore_assigns_a_new_id_when_the_original_is_taken(db_paths):
    occupant_id = _insert_memory(db_paths, content="currently live")

    connection = _connect(db_paths)
    connection.execute(
        """
        INSERT INTO memory_archive (
            memory_id, person_id, layer, content, embedding, access_count,
            created_at, last_accessed, metadata, archived_at, reason
        ) VALUES (?, NULL, 'deep', 'archived content', ?, 1,
                  '2024-01-01T00:00:00Z', NULL, '{}', '2024-02-01T00:00:00Z', 'manual')
        """,
        (occupant_id, json.dumps([0.1]).encode()),
    )
    connection.commit()
    archive_id = connection.execute(
        "SELECT id FROM memory_archive WHERE memory_id = ?", (occupant_id,)
    ).fetchone()[0]
    connection.close()

    restored_id = archive.restore(archive_id)

    assert restored_id != occupant_id
    assert _get_memory(db_paths, occupant_id)["content"] == "currently live"
    restored_row = _get_memory(db_paths, restored_id)
    assert restored_row["content"] == "archived content"
    assert restored_row["layer"] == "deep"


def test_restore_keeps_person_link_when_person_still_exists(db_paths):
    person_id = _insert_person(db_paths, "Ada")
    memory_id = _insert_memory(db_paths, person_id=person_id)
    archive_id = archive.archive_memory(memory_id, reason="manual")

    restored_id = archive.restore(archive_id)

    assert _get_memory(db_paths, restored_id)["person_id"] == person_id


def test_restore_clears_person_link_when_the_person_was_deleted(db_paths):
    person_id = _insert_person(db_paths, "Ada")
    memory_id = _insert_memory(db_paths, person_id=person_id)
    archive_id = archive.archive_memory(memory_id, reason="manual")

    connection = _connect(db_paths)
    connection.execute("DELETE FROM people WHERE id = ?", (person_id,))
    connection.commit()
    connection.close()

    restored_id = archive.restore(archive_id)

    assert _get_memory(db_paths, restored_id)["person_id"] is None


def test_restore_keeps_person_id_zero_as_is(db_paths):
    memory_id = _insert_memory(db_paths, person_id=0)
    archive_id = archive.archive_memory(memory_id, reason="manual")

    restored_id = archive.restore(archive_id)

    assert _get_memory(db_paths, restored_id)["person_id"] == 0


# ---- delete_archived / count -----------------------------------------------------


def test_delete_archived_removes_the_row(db_paths):
    memory_id = _insert_memory(db_paths)
    archive_id = archive.archive_memory(memory_id, reason="manual")

    archive.delete_archived(archive_id)

    assert _get_archive_row(db_paths, archive_id) is None
    with pytest.raises(archive.NotFound):
        archive.delete_archived(archive_id)


def test_count_reflects_the_number_of_archived_rows(db_paths):
    assert archive.count() == 0
    memory_id_1 = _insert_memory(db_paths, content="one")
    memory_id_2 = _insert_memory(db_paths, content="two")
    archive.archive_memory(memory_id_1, reason="manual")
    assert archive.count() == 1
    archive.archive_memory(memory_id_2, reason="manual")
    assert archive.count() == 2


# ---- list_archive -----------------------------------------------------------------


def test_list_archive_orders_newest_first_and_hides_the_embedding(db_paths):
    memory_ids = [_insert_memory(db_paths, content=f"memory {i}") for i in range(3)]
    archive_ids = [archive.archive_memory(memory_id, reason="manual") for memory_id in memory_ids]

    result = archive.list_archive(limit=2, offset=0)

    assert result["total"] == 3
    assert len(result["archive"]) == 2
    returned_ids = [row["id"] for row in result["archive"]]
    assert returned_ids == sorted(archive_ids, reverse=True)[:2]
    for row in result["archive"]:
        assert "embedding" not in row
        assert isinstance(row["metadata"], dict)


def test_list_archive_offset_pages_through_remaining_rows(db_paths):
    memory_ids = [_insert_memory(db_paths, content=f"memory {i}") for i in range(3)]
    for memory_id in memory_ids:
        archive.archive_memory(memory_id, reason="manual")

    page_2 = archive.list_archive(limit=2, offset=2)
    assert len(page_2["archive"]) == 1


# ---- archive_person_memories ------------------------------------------------------


def test_archive_person_memories_archives_exactly_that_persons_rows(db_paths):
    person_id = _insert_person(db_paths, "Ada")
    other_person_id = _insert_person(db_paths, "Bob")
    person_memory_id = _insert_memory(db_paths, person_id=person_id, content="ada's memory")
    other_memory_id = _insert_memory(db_paths, person_id=other_person_id, content="bob's memory")
    general_memory_id = _insert_memory(db_paths, person_id=None, content="general memory")

    connection = _connect(db_paths)
    cursor = connection.cursor()
    archived_count = archive.archive_person_memories(cursor, person_id, now=clock.to_db(NOW))
    connection.commit()
    connection.close()

    assert archived_count == 1
    assert _get_memory(db_paths, person_memory_id) is None
    assert _get_memory(db_paths, other_memory_id) is not None
    assert _get_memory(db_paths, general_memory_id) is not None

    matching = [
        row for row in archive.list_archive()["archive"] if row["memory_id"] == person_memory_id
    ]
    assert len(matching) == 1
    assert matching[0]["reason"] == "person_deleted"
    assert matching[0]["person_id"] == person_id
