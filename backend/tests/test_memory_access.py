"""Tests for memory/access.py's counting rules and their wiring into
toolbox/tools/mem_tool.py's search_memories/add_memory/edit_memory/
list_memories_detailed.

Follows the tmp_path + monkeypatch(toolbox.db.DB_PATH) fixture pattern
from tests/test_dashboard_memory.py -- the real backend/rona.db is never
touched. `memory.schema._reset_heal_cache()` is reset around every test
so the per-path self-heal cache can't leak between tmp_path databases.
"""

import sqlite3
from datetime import datetime, timedelta, timezone

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import app.dashboard as dashboard_module
import create_db
from memory import access as memory_access
from memory import clock as memory_clock
from memory import policy as memory_policy
from memory import schema as memory_schema
from toolbox import db as toolbox_db
from toolbox.tools import mem_tool as mem_tool_module

# Distinct vectors (not derived from text length, unlike the dashboard
# fixture's `_fake_embedding`) so cosine similarity against "query" ranks
# memories in a known, strictly descending order: alpha > beta > gamma >
# delta. That's what lets "only the top N are counted" tests be exact.
_VECTORS = {
    "query": [1.0, 0.0, 0.0],
    "alpha memory": [1.0, 0.0, 0.0],  # score 1.0
    "beta memory": [0.8, 0.6, 0.0],  # score 0.8
    "gamma memory": [0.6, 0.8, 0.0],  # score 0.6
    "delta memory": [0.0, 1.0, 0.0],  # score 0.0
}


def _fake_embedding(text: str, task_type: str) -> list[float]:
    return _VECTORS.get(text, [0.0, 0.0, 1.0])


@pytest.fixture(autouse=True)
def _clean_heal_cache():
    memory_schema._reset_heal_cache()
    yield
    memory_schema._reset_heal_cache()


@pytest.fixture
def db_path(tmp_path, monkeypatch):
    path = tmp_path / "rona.db"
    monkeypatch.setattr(toolbox_db, "DB_PATH", path)
    monkeypatch.setattr(create_db, "DB_PATH", path)
    create_db.create_database()
    monkeypatch.setattr(mem_tool_module, "_get_embedding", _fake_embedding)
    return path


def _set_policy(monkeypatch, **overrides) -> memory_policy.MemoryPolicy:
    fields = {"access_top_n": 2, "access_cooldown_hours": 12, **overrides}
    fixed_policy = memory_policy.MemoryPolicy(**fields)
    monkeypatch.setattr(memory_policy, "current_policy", lambda: fixed_policy)
    return fixed_policy


def _add_memory(content: str, *, layer: str = "short") -> int:
    result = mem_tool_module.add_memory(layer=layer, content=content)
    assert result["success"], result
    return result["id"]


def _add_ranked_memories() -> dict[str, int]:
    return {
        name: _add_memory(f"{name} memory")
        for name in ("alpha", "beta", "gamma", "delta")
    }


def _row(db_path, memory_id: int) -> sqlite3.Row:
    connection = sqlite3.connect(db_path)
    connection.row_factory = sqlite3.Row
    try:
        return connection.execute(
            "SELECT * FROM memories WHERE id = ?", (memory_id,)
        ).fetchone()
    finally:
        connection.close()


def _backdate_last_accessed(db_path, memory_id: int, when: datetime) -> None:
    connection = sqlite3.connect(db_path)
    try:
        connection.execute(
            "UPDATE memories SET last_accessed = ? WHERE id = ?",
            (memory_clock.to_db(when), memory_id),
        )
        connection.commit()
    finally:
        connection.close()


# ---- counted_ids() ---------------------------------------------------------


def test_counted_ids_dedupes_preserves_order_and_caps_at_top_n():
    assert memory_access.counted_ids([5, 3, 5, 1, 3, 7], top_n=3) == [5, 3, 1]


def test_counted_ids_top_n_below_one_returns_empty():
    assert memory_access.counted_ids([1, 2, 3], top_n=0) == []
    assert memory_access.counted_ids([1, 2, 3], top_n=-1) == []


def test_counted_ids_top_n_larger_than_list_returns_everything():
    assert memory_access.counted_ids([1, 2], top_n=10) == [1, 2]


# ---- record_hits() ----------------------------------------------------------


def test_record_hits_empty_ids_is_a_noop():
    connection = sqlite3.connect(":memory:")
    assert memory_access.record_hits(connection, [], now=memory_clock.utc_now(), cooldown_hours=12) == 0
    connection.close()


def test_record_hits_twice_with_same_now_second_call_counts_nothing(db_path):
    memory_id = _add_memory("alpha memory")
    now = memory_clock.utc_now()

    connection = memory_schema.connect()
    try:
        first = memory_access.record_hits(
            connection, [memory_id], now=now, cooldown_hours=12
        )
        second = memory_access.record_hits(
            connection, [memory_id], now=now, cooldown_hours=12
        )
    finally:
        connection.close()

    assert first == 1
    assert second == 0
    row = _row(db_path, memory_id)
    assert row["access_count"] == 1
    assert row["layer_hits"] == 1


# ---- search_memories() only counts the top N ------------------------------


def test_search_memories_only_counts_top_n_results(db_path, monkeypatch):
    _set_policy(monkeypatch, access_top_n=2, access_cooldown_hours=12)
    ids = _add_ranked_memories()

    result = mem_tool_module.search_memories(query="query", limit=10)
    assert result["success"]
    # Sanity check on ranking itself before checking access counting.
    assert [r["id"] for r in result["results"]] == [
        ids["alpha"],
        ids["beta"],
        ids["gamma"],
        ids["delta"],
    ]

    for name in ("alpha", "beta"):
        row = _row(db_path, ids[name])
        assert row["access_count"] == 1
        assert row["layer_hits"] == 1
        assert row["last_accessed"] is not None

    for name in ("gamma", "delta"):
        row = _row(db_path, ids[name])
        assert row["access_count"] == 0
        assert row["layer_hits"] == 0
        assert row["last_accessed"] is None


def test_immediate_second_search_does_not_recount_within_cooldown(db_path, monkeypatch):
    _set_policy(monkeypatch, access_top_n=2, access_cooldown_hours=12)
    ids = _add_ranked_memories()

    mem_tool_module.search_memories(query="query", limit=10)
    mem_tool_module.search_memories(query="query", limit=10)

    row = _row(db_path, ids["alpha"])
    assert row["access_count"] == 1
    assert row["layer_hits"] == 1


def test_search_memories_recounts_after_cooldown_backdated_past(db_path, monkeypatch):
    _set_policy(monkeypatch, access_top_n=2, access_cooldown_hours=12)
    ids = _add_ranked_memories()

    mem_tool_module.search_memories(query="query", limit=10)
    stale = memory_clock.utc_now() - timedelta(hours=13)
    _backdate_last_accessed(db_path, ids["alpha"], stale)

    mem_tool_module.search_memories(query="query", limit=10)

    row = _row(db_path, ids["alpha"])
    assert row["access_count"] == 2
    assert row["layer_hits"] == 2


def test_zero_cooldown_counts_every_search(db_path, monkeypatch):
    _set_policy(monkeypatch, access_top_n=2, access_cooldown_hours=0)
    ids = _add_ranked_memories()

    mem_tool_module.search_memories(query="query", limit=10)
    mem_tool_module.search_memories(query="query", limit=10)
    mem_tool_module.search_memories(query="query", limit=10)

    row = _row(db_path, ids["alpha"])
    assert row["access_count"] == 3
    assert row["layer_hits"] == 3


# ---- untracked search / dashboard endpoint never count ---------------------


def test_search_memories_untracked_never_records_access(db_path, monkeypatch):
    _set_policy(monkeypatch, access_top_n=2, access_cooldown_hours=12)
    ids = _add_ranked_memories()

    result = mem_tool_module.search_memories_untracked(query="query", limit=10)
    assert result["success"]

    for memory_id in ids.values():
        row = _row(db_path, memory_id)
        assert row["access_count"] == 0
        assert row["layer_hits"] == 0
        assert row["last_accessed"] is None


@pytest.fixture
def dashboard_client(db_path):
    test_app = FastAPI()
    test_app.include_router(dashboard_module.router)
    return TestClient(test_app)


def test_dashboard_search_endpoint_never_records_access(
    db_path, monkeypatch, dashboard_client
):
    _set_policy(monkeypatch, access_top_n=2, access_cooldown_hours=12)
    ids = _add_ranked_memories()

    response = dashboard_client.get("/api/data/memories/search", params={"q": "query"})
    assert response.status_code == 200

    for memory_id in ids.values():
        row = _row(db_path, memory_id)
        assert row["access_count"] == 0
        assert row["layer_hits"] == 0
        assert row["last_accessed"] is None


# ---- error tolerance: a broken recorder must not break the search ---------


def test_search_memories_still_succeeds_if_record_hits_raises(db_path, monkeypatch):
    _set_policy(monkeypatch, access_top_n=2, access_cooldown_hours=12)
    _add_ranked_memories()

    def _boom(*args, **kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr(memory_access, "record_hits", _boom)

    result = mem_tool_module.search_memories(query="query", limit=10)
    assert result["success"]
    assert len(result["results"]) == 4


def test_search_memories_still_succeeds_if_current_policy_raises(db_path, monkeypatch):
    _add_ranked_memories()

    def _boom():
        raise RuntimeError("boom")

    monkeypatch.setattr(memory_policy, "current_policy", _boom)

    result = mem_tool_module.search_memories(query="query", limit=10)
    assert result["success"]
    assert len(result["results"]) == 4


# ---- add_memory / edit_memory keep layer bookkeeping correct ---------------


def test_add_memory_sets_layer_since_and_zero_layer_hits(db_path):
    memory_id = _add_memory("alpha memory", layer="short")
    row = _row(db_path, memory_id)
    assert row["layer_since"] is not None
    assert memory_clock.from_db(row["layer_since"]) is not None
    assert row["layer_hits"] == 0


def test_edit_memory_content_only_keeps_layer_counters(db_path, monkeypatch):
    times = iter([datetime(2024, 1, 1, tzinfo=timezone.utc)])
    monkeypatch.setattr(memory_clock, "utc_now", lambda: next(times))
    memory_id = _add_memory("alpha memory", layer="short")

    connection = sqlite3.connect(db_path)
    connection.execute(
        "UPDATE memories SET layer_hits = 5, access_count = 5 WHERE id = ?",
        (memory_id,),
    )
    connection.commit()
    connection.close()
    before = _row(db_path, memory_id)

    result = mem_tool_module.edit_memory(memory_id=memory_id, content="alpha memory v2")
    assert result["success"], result

    after = _row(db_path, memory_id)
    assert after["layer"] == "short"
    assert after["layer_hits"] == before["layer_hits"] == 5
    assert after["layer_since"] == before["layer_since"]


def test_edit_memory_same_layer_keeps_layer_counters(db_path, monkeypatch):
    times = iter([datetime(2024, 1, 1, tzinfo=timezone.utc), datetime(2024, 1, 2, tzinfo=timezone.utc)])
    monkeypatch.setattr(memory_clock, "utc_now", lambda: next(times))
    memory_id = _add_memory("alpha memory", layer="short")

    connection = sqlite3.connect(db_path)
    connection.execute(
        "UPDATE memories SET layer_hits = 5, access_count = 5 WHERE id = ?",
        (memory_id,),
    )
    connection.commit()
    connection.close()
    before = _row(db_path, memory_id)

    result = mem_tool_module.edit_memory(memory_id=memory_id, layer="short")
    assert result["success"], result

    after = _row(db_path, memory_id)
    assert after["layer"] == "short"
    assert after["layer_hits"] == before["layer_hits"] == 5
    assert after["layer_since"] == before["layer_since"]


def test_edit_memory_real_layer_change_resets_hits_and_updates_since(db_path, monkeypatch):
    t0 = datetime(2024, 1, 1, tzinfo=timezone.utc)
    t1 = datetime(2024, 1, 2, tzinfo=timezone.utc)
    times = iter([t0, t1])
    monkeypatch.setattr(memory_clock, "utc_now", lambda: next(times))
    memory_id = _add_memory("alpha memory", layer="short")

    connection = sqlite3.connect(db_path)
    connection.execute(
        "UPDATE memories SET layer_hits = 5, access_count = 5 WHERE id = ?",
        (memory_id,),
    )
    connection.commit()
    connection.close()
    before = _row(db_path, memory_id)
    assert before["layer_since"] == memory_clock.to_db(t0)

    result = mem_tool_module.edit_memory(memory_id=memory_id, layer="seasonal")
    assert result["success"], result

    after = _row(db_path, memory_id)
    assert after["layer"] == "seasonal"
    assert after["layer_hits"] == 0
    assert after["access_count"] == 5  # lifetime counter, untouched
    assert after["layer_since"] == memory_clock.to_db(t1)
    assert after["layer_since"] != before["layer_since"]


# ---- list_memories_detailed() ----------------------------------------------


def test_list_memories_detailed_includes_bookkeeping_fields_and_total(db_path, monkeypatch):
    _set_policy(monkeypatch, access_top_n=2, access_cooldown_hours=12)
    _add_ranked_memories()
    mem_tool_module.search_memories(query="query", limit=10)

    result = mem_tool_module.list_memories_detailed(limit=10, offset=0)
    assert result["success"]
    assert result["total"] == 4
    for memory in result["memories"]:
        for field in ("access_count", "layer_hits", "layer_since", "last_accessed"):
            assert field in memory


def test_list_memories_detailed_layer_filter(db_path):
    _add_memory("alpha memory", layer="short")
    _add_memory("beta memory", layer="deep")

    result = mem_tool_module.list_memories_detailed(layer="deep")
    assert result["success"]
    assert result["total"] == 1
    assert result["memories"][0]["layer"] == "deep"


def test_list_memories_detailed_invalid_layer_fails(db_path):
    result = mem_tool_module.list_memories_detailed(layer="not-a-layer")
    assert result["success"] is False
