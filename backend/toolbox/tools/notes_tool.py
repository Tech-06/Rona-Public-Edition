import sqlite3
from datetime import datetime

from toolbox import db


def _get_connection() -> sqlite3.Connection:
    return db.connect()


def add_note(title: str, body: str) -> dict:
    try:
        connection = _get_connection()
        cursor = connection.cursor()
        date_str = datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S")

        cursor.execute(
            "INSERT INTO notes (title, body, date) VALUES (?, ?, ?)",
            (title, body, date_str),
        )
        connection.commit()
        note_id = cursor.lastrowid
        connection.close()
        return {"success": True, "id": note_id, "message": "Note added successfully."}
    except Exception as exc:  # noqa: BLE001
        return {"success": False, "error": str(exc)}


def get_notes(limit: int = 50, offset: int = 0) -> dict:
    try:
        connection = _get_connection()
        cursor = connection.cursor()
        cursor.execute(
            "SELECT id, title, body, date FROM notes ORDER BY id DESC LIMIT ? OFFSET ?",
            (limit, offset),
        )
        rows = cursor.fetchall()
        connection.close()

        notes = [
            {
                "id": r["id"],
                "title": r["title"],
                "body": r["body"],
                "date": r["date"],
            }
            for r in rows
        ]
        return {"success": True, "notes": notes}
    except Exception as exc:  # noqa: BLE001
        return {"success": False, "error": str(exc)}


def edit_note(note_id: int, title: str | None = None, body: str | None = None) -> dict:
    try:
        if title is None and body is None:
            return {"success": False, "error": "No fields selected to update."}

        connection = _get_connection()
        cursor = connection.cursor()

        updates = []
        params = []
        if title is not None:
            updates.append("title = ?")
            params.append(title)
        if body is not None:
            updates.append("body = ?")
            params.append(body)

        params.append(note_id)

        query = f"UPDATE notes SET {', '.join(updates)} WHERE id = ?"
        cursor.execute(query, params)

        if cursor.rowcount == 0:
            connection.close()
            return {"success": False, "error": f"ID {note_id} not found."}

        connection.commit()
        connection.close()
        return {"success": True, "message": "Note updated successfully."}
    except Exception as exc:  # noqa: BLE001
        return {"success": False, "error": str(exc)}


def delete_note(note_id: int) -> dict:
    try:
        connection = _get_connection()
        cursor = connection.cursor()
        cursor.execute("DELETE FROM notes WHERE id = ?", (note_id,))

        if cursor.rowcount == 0:
            connection.close()
            return {"success": False, "error": f"ID {note_id} not found."}

        connection.commit()
        connection.close()
        return {"success": True, "message": "Note deleted successfully."}
    except Exception as exc:  # noqa: BLE001
        return {"success": False, "error": str(exc)}
