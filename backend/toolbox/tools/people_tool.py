import sqlite3

from toolbox import db

_SEARCH_FIELDS = ("name", "nickname", "connection")


def _get_connection() -> sqlite3.Connection:
    return db.connect()


def _row_to_dict(row: sqlite3.Row) -> dict:
    return {
        "id": row["id"],
        "name": row["name"],
        "surname": row["surname"],
        "nickname": row["nickname"],
        "connection": row["connection"],
        "phone_num": row["phone_num"],
        "mail": row["mail"],
        "birthday": row["birthday"],
        "address": row["address"],
    }


def add_person(
    name: str,
    surname: str | None = None,
    nickname: str | None = None,
    connection: str | None = None,
    phone_num: str | None = None,
    mail: str | None = None,
    birthday: str | None = None,
    address: str | None = None,
) -> dict:
    try:
        connection_db = _get_connection()
        cursor = connection_db.cursor()

        query = """
            INSERT INTO people (name, surname, nickname, connection, phone_num, mail, birthday, address)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """
        params = (
            name,
            surname,
            nickname,
            connection,
            phone_num,
            mail,
            birthday,
            address,
        )
        cursor.execute(query, params)
        connection_db.commit()
        person_id = cursor.lastrowid
        connection_db.close()

        return {
            "success": True,
            "id": person_id,
            "message": "Person added successfully.",
        }
    except Exception as exc:  # noqa: BLE001
        return {"success": False, "error": str(exc)}


def delete_person(person_id: int) -> dict:
    try:
        connection_db = _get_connection()
        cursor = connection_db.cursor()
        cursor.execute("DELETE FROM people WHERE id = ?", (person_id,))

        if cursor.rowcount == 0:
            connection_db.close()
            return {"success": False, "error": f"ID {person_id} not found."}

        connection_db.commit()
        connection_db.close()
        return {"success": True, "message": "Person deleted successfully."}
    except Exception as exc:  # noqa: BLE001
        return {"success": False, "error": str(exc)}


def edit_person(
    person_id: int,
    name: str | None = None,
    surname: str | None = None,
    nickname: str | None = None,
    connection: str | None = None,
    phone_num: str | None = None,
    mail: str | None = None,
    birthday: str | None = None,
    address: str | None = None,
) -> dict:
    try:
        fields = {
            "name": name,
            "surname": surname,
            "nickname": nickname,
            "connection": connection,
            "phone_num": phone_num,
            "mail": mail,
            "birthday": birthday,
            "address": address,
        }

        updates = []
        params = []
        for col, val in fields.items():
            if val is not None:
                updates.append(f"{col} = ?")
                params.append(val)

        if not updates:
            return {"success": False, "error": "No fields provided to update."}

        params.append(person_id)

        connection_db = _get_connection()
        cursor = connection_db.cursor()
        query = f"UPDATE people SET {', '.join(updates)} WHERE id = ?"
        cursor.execute(query, params)

        if cursor.rowcount == 0:
            connection_db.close()
            return {"success": False, "error": f"ID {person_id} not found."}

        connection_db.commit()
        connection_db.close()
        return {"success": True, "message": "Person updated successfully."}
    except Exception as exc:  # noqa: BLE001
        return {"success": False, "error": str(exc)}


def get_people() -> dict:
    try:
        connection_db = _get_connection()
        cursor = connection_db.cursor()
        cursor.execute("SELECT * FROM people ORDER BY id ASC")
        rows = cursor.fetchall()
        connection_db.close()

        people_list = [_row_to_dict(r) for r in rows]
        return {"success": True, "people": people_list}
    except Exception as exc:  # noqa: BLE001
        return {"success": False, "error": str(exc)}


def search_person(query: str, search_field: str | None = None) -> dict:
    try:
        connection_db = _get_connection()
        cursor = connection_db.cursor()

        q = f"%{query}%"

        if search_field:
            if search_field not in _SEARCH_FIELDS:
                connection_db.close()
                return {
                    "success": False,
                    "error": "Invalid search_field. Only 'name', 'nickname', "
                    "'connection' are allowed.",
                }

            sql = f"SELECT * FROM people WHERE {search_field} LIKE ?"
            cursor.execute(sql, (q,))
            rows = cursor.fetchall()
            results = [_row_to_dict(r) for r in rows]

        else:
            sql = """
                SELECT *,
                       CASE
                           WHEN name LIKE ? THEN 1
                           WHEN nickname LIKE ? THEN 2
                           WHEN connection LIKE ? THEN 3
                       END as match_priority
                FROM people
                WHERE name LIKE ? OR nickname LIKE ? OR connection LIKE ?
                ORDER BY match_priority ASC, id ASC
            """
            params = (q, q, q, q, q, q)
            cursor.execute(sql, params)
            rows = cursor.fetchall()
            results = [_row_to_dict(r) for r in rows]

        connection_db.close()
        return {"success": True, "results": results}
    except Exception as exc:  # noqa: BLE001
        return {"success": False, "error": str(exc)}
