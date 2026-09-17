import json
import math
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from google import genai
from google.genai import types

from toolbox import db

load_dotenv(Path(__file__).resolve().parents[2] / ".env")

_LAYERS = ("deep", "seasonal", "short")
_DATE_FORMAT = "%Y-%m-%dT%H:%M:%SZ"
_INVALID_LAYER_ERROR = "Invalid layer. Only 'deep', 'seasonal' or 'short' are allowed."

_client: genai.Client | None = None


def _get_connection() -> sqlite3.Connection:
    return db.connect()


def _check_person_exists(cursor: sqlite3.Cursor, person_id: int | None) -> bool:
    if person_id is None or person_id == 0:
        return True
    cursor.execute("SELECT id FROM people WHERE id = ?", (person_id,))
    return cursor.fetchone() is not None


def _get_client() -> genai.Client:
    global _client
    if _client is None:
        _client = genai.Client(api_key=os.getenv("GOOGLE_API_KEY", ""))
    return _client


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

        embedding_blob = json.dumps(
            _get_embedding(content, "RETRIEVAL_DOCUMENT")
        ).encode("utf-8")
        meta_str = json.dumps(metadata) if metadata else "{}"

        cursor.execute(
            """
            INSERT INTO memories (person_id, layer, content, embedding, metadata)
            VALUES (?, ?, ?, ?, ?)
            """,
            (person_id, layer, content, embedding_blob, meta_str),
        )
        connection.commit()
        memory_id = cursor.lastrowid
        return {
            "success": True,
            "id": memory_id,
            "message": "Memory added successfully.",
        }
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
            updates.append("layer = ?")
            params.append(layer)
        if content is not None:
            embedding_blob = json.dumps(
                _get_embedding(content, "RETRIEVAL_DOCUMENT")
            ).encode("utf-8")
            updates.append("content = ?")
            params.append(content)
            updates.append("embedding = ?")
            params.append(embedding_blob)
        if metadata is not None:
            updates.append("metadata = ?")
            params.append(json.dumps(metadata))

        params.append(memory_id)
        cursor.execute(f"UPDATE memories SET {', '.join(updates)} WHERE id = ?", params)
        if cursor.rowcount == 0:
            return {"success": False, "error": f"ID {memory_id} not found."}

        connection.commit()
        return {"success": True, "message": "Memory updated successfully."}
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
            f"SELECT id, person_id, content, created_at, metadata "
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


def search_memories(
    query: str,
    person: int | str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    limit: int = 10,
) -> dict:
    connection = None
    try:
        if not query or not query.strip():
            return {"success": False, "error": "Query text is required."}

        scope = _validate_person(person)
        conditions, params = _resolve_filters(scope, date_from, date_to)

        query_embedding = _get_embedding(query, "RETRIEVAL_QUERY")

        connection = _get_connection()
        cursor = connection.cursor()
        cursor.execute(
            f"SELECT id, person_id, content, created_at, metadata, embedding "
            f"FROM memories{_where_clause(conditions)}",
            params,
        )
        rows = cursor.fetchall()

        scored = []
        for row in rows:
            stored = json.loads(row["embedding"])
            if len(stored) != len(query_embedding):
                continue
            score = _cosine_similarity(query_embedding, stored)
            scored.append((score, row))
        scored.sort(key=lambda item: item[0], reverse=True)
        top = scored[:limit]

        if top:
            placeholders = ", ".join("?" * len(top))
            cursor.execute(
                f"UPDATE memories SET access_count = access_count + 1, "
                f"last_accessed = strftime('{_DATE_FORMAT}', 'now') "
                f"WHERE id IN ({placeholders})",
                [row["id"] for _, row in top],
            )
            connection.commit()

        results = [
            {**_row_to_memory(row), "score": round(score, 4)} for score, row in top
        ]
        return {"success": True, "results": results}
    except Exception as exc:  # noqa: BLE001
        return {"success": False, "error": str(exc)}
    finally:
        if connection is not None:
            connection.close()
