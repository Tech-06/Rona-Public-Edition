import json
import logging
import math
import os
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from google import genai
from google.genai import types

import i18n
from memory import access as memory_access
from memory import clock as memory_clock
from memory import policy as memory_policy
from memory import schema as memory_schema
from toolbox import untrusted

load_dotenv(Path(__file__).resolve().parents[2] / ".env")

_LAYERS = ("deep", "seasonal", "short")
_DATE_FORMAT = "%Y-%m-%dT%H:%M:%SZ"
_INVALID_LAYER_ERROR = "Invalid layer. Only 'deep', 'seasonal' or 'short' are allowed."

_client: genai.Client | None = None
# The key the cached client was built with, so a changed GOOGLE_API_KEY
# (edited in the dashboard, no restart) rebuilds the client instead of
# silently using the old one.
_client_key: str | None = None

# `memories.embedding` is NOT NULL on existing databases (SQLite cannot drop
# a constraint), so "no embedding yet" is stored as an empty blob.
_NO_EMBEDDING = b""

_KEYWORD_NOTE = (
    "Keyword mode: the embedding model is unavailable (missing API key or "
    "failed call), so results are case-insensitive keyword matches, not "
    "semantic ones."
)


def _get_connection() -> sqlite3.Connection:
    return memory_schema.connect()


def _check_person_exists(cursor: sqlite3.Cursor, person_id: int | None) -> bool:
    if person_id is None or person_id == 0:
        return True
    cursor.execute("SELECT id FROM people WHERE id = ?", (person_id,))
    return cursor.fetchone() is not None


def _get_client() -> genai.Client:
    global _client, _client_key
    api_key = os.getenv("GOOGLE_API_KEY", "")
    if _client is None or _client_key != api_key:
        _client = genai.Client(api_key=api_key)
        _client_key = api_key
    return _client


def _current_model() -> str:
    return (os.getenv("EMBEDDING_MODEL_NAME") or "").strip()


def _ensure_embedding_model_column(connection: sqlite3.Connection) -> None:
    """Self-heal for databases that haven't re-run create_db.py since
    migration 5 -- the column is nullable, so a plain ALTER is safe."""
    columns = {row[1] for row in connection.execute("PRAGMA table_info(memories)")}
    if "embedding_model" not in columns:
        connection.execute("ALTER TABLE memories ADD COLUMN embedding_model TEXT")
        connection.commit()


def _ensure_source_column(connection: sqlite3.Connection) -> None:
    """Self-heal for databases that haven't re-run create_db.py since
    migration 6 (nullable, so a plain ALTER is safe)."""
    columns = {row[1] for row in connection.execute("PRAGMA table_info(memories)")}
    if "source" not in columns:
        connection.execute("ALTER TABLE memories ADD COLUMN source TEXT")
        connection.commit()


def memory_layer(memory_id: int) -> str | None:
    """Current layer of a memory, or None when it does not exist or the
    database cannot be read. Read-only: the confirmation decision uses it to
    see what an edit would touch (edit_memory(memory_id=1, content=...) on a
    deep memory names no layer in its arguments)."""
    connection = None
    try:
        connection = _get_connection()
        row = connection.execute(
            "SELECT layer FROM memories WHERE id = ?", (memory_id,)
        ).fetchone()
        return row["layer"] if row is not None else None
    except Exception:  # noqa: BLE001
        return None
    finally:
        if connection is not None:
            connection.close()


def _current_source() -> str:
    # Set by the graph around tool execution; memories written after the
    # assistant read outside content are flagged so they can be reviewed.
    return "untrusted_context" if untrusted.current_taint() else "user"


def _try_embedding(text: str, task_type: str) -> tuple[list[float] | None, str | None]:
    """(vector, model_name), or (None, None) if embedding is unavailable.
    Memory must keep working without a Gemini key, so failure here is
    degraded behaviour, never an error."""
    try:
        return _get_embedding(text, task_type), (_current_model() or None)
    except Exception as exc:  # noqa: BLE001
        logging.getLogger("uvicorn.error").warning(
            i18n.t("memory.log_embedding_unavailable"), exc
        )
        return None, None


def _get_embedding(text: str, task_type: str) -> list[float]:
    api_key = os.getenv("GOOGLE_API_KEY")
    model_name = os.getenv("EMBEDDING_MODEL_NAME")
    if not api_key:
        raise RuntimeError("GOOGLE_API_KEY is not set.")
    if not model_name:
        raise RuntimeError("EMBEDDING_MODEL_NAME is not set.")
    response = _get_client().models.embed_content(
        model=model_name,
        contents=text,
        config=types.EmbedContentConfig(task_type=task_type),
    )
    return response.embeddings[0].values


def _validate_person(person: Any) -> int | str | None:
    if person is None:
        return None
    if isinstance(person, int) and not isinstance(person, bool) and person >= 0:
        return person
    if isinstance(person, str) and person.strip().isdigit():
        return int(person.strip())
    if person == "all":
        return "all"
    raise ValueError(
        "Invalid person value. Provide a non-negative integer ID, 'all', "
        "or omit to target general memories."
    )


def _normalize_date_bound(value: str, field: str, *, is_end: bool) -> str:
    raw = value.strip()
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError:
        raise ValueError(
            f"Invalid {field}. Use ISO 8601 date (YYYY-MM-DD) or date-time."
        ) from None
    if parsed.tzinfo is not None:
        parsed = parsed.astimezone(timezone.utc).replace(tzinfo=None)
    if is_end and len(raw) == 10:
        parsed = parsed.replace(hour=23, minute=59, second=59, microsecond=0)
    return parsed.strftime(_DATE_FORMAT)


def _resolve_filters(
    person: int | str | None, date_from: str | None, date_to: str | None
) -> tuple[list[str], list[Any]]:
    conditions: list[str] = []
    params: list[Any] = []
    if person == "all":
        pass
    elif person is None:
        conditions.append("person_id IS NULL")
    else:
        conditions.append("person_id = ?")
        params.append(person)
    if date_from is not None:
        conditions.append("created_at >= ?")
        params.append(_normalize_date_bound(date_from, "date_from", is_end=False))
    if date_to is not None:
        conditions.append("created_at <= ?")
        params.append(_normalize_date_bound(date_to, "date_to", is_end=True))
    return conditions, params


def _where_clause(conditions: list[str]) -> str:
    if not conditions:
        return ""
    return f" WHERE {' AND '.join(conditions)}"


def _row_to_memory(row: sqlite3.Row) -> dict:
    return {
        "id": row["id"],
        "person_id": row["person_id"],
        "layer": row["layer"],
        "content": row["content"],
        "created_at": row["created_at"],
        "metadata": json.loads(row["metadata"]) if row["metadata"] else {},
    }


def _cosine_similarity(vec_a: list[float], vec_b: list[float]) -> float:
    dot_product = sum(a * b for a, b in zip(vec_a, vec_b))
    norm_a = math.sqrt(sum(a * a for a in vec_a))
    norm_b = math.sqrt(sum(b * b for b in vec_b))
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return dot_product / (norm_a * norm_b)


def add_memory(
    layer: str, content: str, person_id: int | None = None, metadata: dict | None = None
) -> dict:
    connection = None
    try:
        if layer not in _LAYERS:
            return {"success": False, "error": _INVALID_LAYER_ERROR}
        if not content or not content.strip():
            return {"success": False, "error": "Content is required."}

        connection = _get_connection()
        cursor = connection.cursor()

        if not _check_person_exists(cursor, person_id):
            return {
                "success": False,
                "error": f"Person with ID {person_id} not found in people table.",
            }

        vector, model_name = _try_embedding(content, "RETRIEVAL_DOCUMENT")
        embedding_blob = (
            json.dumps(vector).encode("utf-8") if vector is not None else _NO_EMBEDDING
        )
        meta_str = json.dumps(metadata) if metadata else "{}"

        _ensure_embedding_model_column(connection)
        _ensure_source_column(connection)
        cursor.execute(
            """
            INSERT INTO memories
                (person_id, layer, content, embedding, embedding_model, metadata,
                 layer_since, layer_hits, source)
            VALUES (?, ?, ?, ?, ?, ?, ?, 0, ?)
            """,
            (
                person_id,
                layer,
                content,
                embedding_blob,
                model_name,
                meta_str,
                memory_clock.to_db(memory_clock.utc_now()),
                _current_source(),
            ),
        )
        connection.commit()
        memory_id = cursor.lastrowid
        result = {
            "success": True,
            "id": memory_id,
            "message": "Memory added successfully.",
        }
        if vector is None:
            result["embedded"] = False
            result["message"] = (
                "Memory added without an embedding (embedding model unavailable); "
                "it is findable by keyword search only until it is re-embedded."
            )
        return result
    except Exception as exc:  # noqa: BLE001
        return {"success": False, "error": str(exc)}
    finally:
        if connection is not None:
            connection.close()


def edit_memory(
    memory_id: int,
    layer: str | None = None,
    content: str | None = None,
    person_id: int | None = None,
    metadata: dict | None = None,
) -> dict:
    connection = None
    try:
        if layer is None and content is None and person_id is None and metadata is None:
            return {"success": False, "error": "No fields selected to update."}
        if layer is not None and layer not in _LAYERS:
            return {"success": False, "error": _INVALID_LAYER_ERROR}

        connection = _get_connection()
        cursor = connection.cursor()

        if person_id is not None and not _check_person_exists(cursor, person_id):
            return {
                "success": False,
                "error": f"Person with ID {person_id} not found in people table.",
            }

        updates = []
        params = []

        if person_id is not None:
            updates.append("person_id = ?")
            params.append(person_id)
        if layer is not None:
            # SET expressions see the row's OLD values, so comparing
            # `layer = ?` against the not-yet-updated column here is what
            # lets a real layer change reset the per-layer counters while a
            # same-layer edit (e.g. touching only content) leaves them
            # alone -- all in one atomic UPDATE.
            now_db = memory_clock.to_db(memory_clock.utc_now())
            updates.append("layer_since = CASE WHEN layer = ? THEN layer_since ELSE ? END")
            params.extend([layer, now_db])
            updates.append("layer_hits = CASE WHEN layer = ? THEN layer_hits ELSE 0 END")
            params.append(layer)
            updates.append("layer = ?")
            params.append(layer)
        embedded = True
        if content is not None:
            vector, model_name = _try_embedding(content, "RETRIEVAL_DOCUMENT")
            embedded = vector is not None
            embedding_blob = (
                json.dumps(vector).encode("utf-8") if embedded else _NO_EMBEDDING
            )
            _ensure_embedding_model_column(connection)
            updates.append("content = ?")
            params.append(content)
            updates.append("embedding = ?")
            params.append(embedding_blob)
            updates.append("embedding_model = ?")
            params.append(model_name)
        if metadata is not None:
            updates.append("metadata = ?")
            params.append(json.dumps(metadata))

        if layer is not None or content is not None or person_id is not None:
            # An edit made after reading outside content taints the row's
            # provenance; a clean edit never launders an earlier flag.
            if untrusted.current_taint():
                _ensure_source_column(connection)
                updates.append("source = ?")
                params.append("untrusted_context")

        params.append(memory_id)
        cursor.execute(f"UPDATE memories SET {', '.join(updates)} WHERE id = ?", params)
        if cursor.rowcount == 0:
            return {"success": False, "error": f"ID {memory_id} not found."}

        connection.commit()
        result = {"success": True, "message": "Memory updated successfully."}
        if not embedded:
            result["embedded"] = False
            result["message"] = (
                "Memory updated without an embedding (embedding model unavailable); "
                "it is findable by keyword search only until it is re-embedded."
            )
        return result
    except Exception as exc:  # noqa: BLE001
        return {"success": False, "error": str(exc)}
    finally:
        if connection is not None:
            connection.close()


def delete_memory(memory_id: int) -> dict:
    connection = None
    try:
        connection = _get_connection()
        cursor = connection.cursor()
        cursor.execute("DELETE FROM memories WHERE id = ?", (memory_id,))

        if cursor.rowcount == 0:
            return {"success": False, "error": f"ID {memory_id} not found."}

        connection.commit()
        return {"success": True, "message": "Memory deleted successfully."}
    except Exception as exc:  # noqa: BLE001
        return {"success": False, "error": str(exc)}
    finally:
        if connection is not None:
            connection.close()


def get_memories(
    limit: int = 100,
    offset: int = 0,
    person: int | str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
) -> dict:
    connection = None
    try:
        scope = _validate_person(person)
        conditions, params = _resolve_filters(scope, date_from, date_to)

        connection = _get_connection()
        cursor = connection.cursor()
        cursor.execute(
            f"SELECT id, person_id, layer, content, created_at, metadata "
            f"FROM memories{_where_clause(conditions)} "
            f"ORDER BY id DESC LIMIT ? OFFSET ?",
            (*params, limit, offset),
        )
        rows = cursor.fetchall()
        memories = [_row_to_memory(r) for r in rows]
        return {"success": True, "memories": memories}
    except Exception as exc:  # noqa: BLE001
        return {"success": False, "error": str(exc)}
    finally:
        if connection is not None:
            connection.close()


def _keyword_search(rows: list[sqlite3.Row], query: str, limit: int) -> dict:
    """Fallback when no query embedding can be made: case-insensitive term
    matching over content and the metadata text, best match count first,
    then newest. Filters were already applied in SQL by the caller."""
    terms = list(dict.fromkeys(re.findall(r"\w+", query.casefold())))
    scored = []
    for row in rows:
        haystack = f"{row['content']} {row['metadata'] or ''}".casefold()
        matched = sum(1 for term in terms if term in haystack)
        if matched:
            scored.append((matched, row["created_at"], row["id"], row))
    scored.sort(key=lambda item: (item[0], item[1], item[2]), reverse=True)
    results = [
        {**_row_to_memory(row), "score": round(matched / len(terms), 4)}
        for matched, _, _, row in scored[:limit]
    ]
    return {
        "success": True,
        "results": results,
        "mode": "keyword",
        "note": _KEYWORD_NOTE,
    }


def _search(
    query: str,
    person: int | str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    limit: int = 10,
) -> dict:
    """Semantic search with no side effects -- the shared implementation
    behind both the LLM-facing `search_memories` (which records access)
    and `search_memories_untracked` (dashboard/CLI lookups, which don't).
    """
    connection = None
    try:
        if not query or not query.strip():
            return {"success": False, "error": "Query text is required."}

        scope = _validate_person(person)
        conditions, params = _resolve_filters(scope, date_from, date_to)

        query_embedding, _ = _try_embedding(query, "RETRIEVAL_QUERY")

        connection = _get_connection()
        _ensure_embedding_model_column(connection)
        cursor = connection.cursor()
        cursor.execute(
            f"SELECT id, person_id, layer, content, created_at, metadata, "
            f"embedding, embedding_model FROM memories{_where_clause(conditions)}",
            params,
        )
        rows = cursor.fetchall()

        if query_embedding is None:
            return _keyword_search(rows, query, limit)

        current_model = _current_model()
        scored = []
        skipped_model = skipped_dim = skipped_bad = skipped_unembedded = legacy = 0
        for row in rows:
            row_model = row["embedding_model"]
            if row_model is not None and current_model and row_model != current_model:
                # Same dimension from a different model still gives
                # meaningless cosine scores, so don't compare at all.
                skipped_model += 1
                continue
            if not row["embedding"]:
                skipped_unembedded += 1
                continue
            try:
                stored = json.loads(row["embedding"])
                if not isinstance(stored, list):
                    raise ValueError("embedding is not a list")
                if len(stored) != len(query_embedding):
                    skipped_dim += 1
                    continue
                score = _cosine_similarity(query_embedding, stored)
            except (ValueError, TypeError):
                skipped_bad += 1
                continue
            if row_model is None:
                legacy += 1
            scored.append((score, row))
        scored.sort(key=lambda item: item[0], reverse=True)
        top = scored[:limit]

        results = [
            {**_row_to_memory(row), "score": round(score, 4)} for score, row in top
        ]
        result = {"success": True, "results": results}
        skipped = skipped_model + skipped_dim + skipped_bad + skipped_unembedded
        if skipped or legacy:
            logging.getLogger("uvicorn.error").warning(
                i18n.t("memory.log_search_skipped"),
                skipped_model,
                skipped_dim,
                skipped_bad,
                skipped_unembedded,
                legacy,
            )
        if skipped:
            result["skipped"] = {
                "other_model": skipped_model,
                "dimension_mismatch": skipped_dim,
                "malformed": skipped_bad,
                "not_embedded": skipped_unembedded,
            }
            result["note"] = (
                f"{skipped} memories were not searched because their embeddings "
                "are missing, malformed or from a different embedding model; "
                "they may need re-embedding."
            )
        return result
    except Exception as exc:  # noqa: BLE001
        return {"success": False, "error": str(exc)}
    finally:
        if connection is not None:
            connection.close()


def _record_access(memory_ids: list[int]) -> None:
    """Count a recall for the top-scoring ids of an LLM `search_memories`
    call. Never allowed to fail the search it's attached to: any error
    (bad policy settings, a locked database, ...) is logged and swallowed.
    """
    try:
        policy = memory_policy.current_policy()
        counted = memory_access.counted_ids(memory_ids, policy.access_top_n)
        connection = _get_connection()
        try:
            memory_access.record_hits(
                connection,
                counted,
                now=memory_clock.utc_now(),
                cooldown_hours=policy.access_cooldown_hours,
            )
        finally:
            connection.close()
    except Exception as exc:  # noqa: BLE001
        logging.getLogger("uvicorn.error").warning(i18n.t("memory.log_access_failed"), exc)


def search_memories(
    query: str,
    person: int | str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    limit: int = 10,
) -> dict:
    """The LLM-facing memory search tool. Recalling a memory this way is
    what counts as "access" for the layer lifecycle -- see
    `_record_access()` and `memory/access.py`.
    """
    result = _search(query, person=person, date_from=date_from, date_to=date_to, limit=limit)
    if result["success"]:
        _record_access([r["id"] for r in result["results"]])
    return result


def search_memories_untracked(
    query: str,
    person: int | str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    limit: int = 10,
) -> dict:
    """Same search, for the web dashboard and CLI -- deliberately not
    registered as an LLM tool in tools.json, and never records access.
    """
    return _search(query, person=person, date_from=date_from, date_to=date_to, limit=limit)


def list_memories_detailed(
    limit: int = 100,
    offset: int = 0,
    person: int | str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    layer: str | None = None,
) -> dict:
    """Admin listing for the web dashboard/CLI -- not an LLM-facing tool
    (deliberately not registered in tools.json). Same rows as
    `get_memories`/`search_memories` plus the layer-lifecycle bookkeeping
    fields (`access_count`, `layer_hits`, `layer_since`, `last_accessed`)
    those never expose to the LLM.
    """
    connection = None
    try:
        if layer is not None and layer not in _LAYERS:
            return {"success": False, "error": _INVALID_LAYER_ERROR}

        scope = _validate_person(person)
        conditions, params = _resolve_filters(scope, date_from, date_to)
        if layer is not None:
            conditions.append("layer = ?")
            params.append(layer)
        where = _where_clause(conditions)

        connection = _get_connection()
        cursor = connection.cursor()
        cursor.execute(
            f"SELECT id, person_id, layer, content, created_at, metadata, "
            f"access_count, layer_hits, layer_since, last_accessed "
            f"FROM memories{where} "
            f"ORDER BY id DESC LIMIT ? OFFSET ?",
            (*params, limit, offset),
        )
        rows = cursor.fetchall()
        memories = [
            {
                **_row_to_memory(row),
                "access_count": row["access_count"],
                "layer_hits": row["layer_hits"],
                "layer_since": row["layer_since"],
                "last_accessed": row["last_accessed"],
            }
            for row in rows
        ]

        cursor.execute(f"SELECT COUNT(*) FROM memories{where}", params)
        total = cursor.fetchone()[0]

        return {"success": True, "memories": memories, "total": total}
    except Exception as exc:  # noqa: BLE001
        return {"success": False, "error": str(exc)}
    finally:
        if connection is not None:
            connection.close()


def memory_stats() -> dict:
    """Aggregate counts for the dashboard/CLI -- not an LLM-facing tool

    (deliberately not registered in tools.json).
    """
    connection = None
    try:
        connection = _get_connection()
        cursor = connection.cursor()

        cursor.execute("SELECT layer, COUNT(*) FROM memories GROUP BY layer")
        by_layer_counts = dict(cursor.fetchall())

        cursor.execute("SELECT COUNT(*) FROM memories")
        total = cursor.fetchone()[0]

        cursor.execute("SELECT COUNT(*) FROM memories WHERE person_id IS NULL")
        general_count = cursor.fetchone()[0]

        cursor.execute("SELECT MIN(created_at), MAX(created_at) FROM memories")
        oldest_created_at, newest_created_at = cursor.fetchone()

        cursor.execute("SELECT COALESCE(SUM(access_count), 0) FROM memories")
        total_access_count = cursor.fetchone()[0]

        return {
            "success": True,
            "total": total,
            "by_layer": {layer: by_layer_counts.get(layer, 0) for layer in _LAYERS},
            "general_count": general_count,
            "person_linked_count": total - general_count,
            "oldest_created_at": oldest_created_at,
            "newest_created_at": newest_created_at,
            "total_access_count": total_access_count,
        }
    except Exception as exc:  # noqa: BLE001
        return {"success": False, "error": str(exc)}
    finally:
        if connection is not None:
            connection.close()
