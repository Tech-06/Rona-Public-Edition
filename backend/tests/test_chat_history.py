from datetime import datetime, timedelta, timezone

import pytest

from graph import conversations, history, threads
from toolbox import db as toolbox_db


@pytest.fixture
def db_path(tmp_path, monkeypatch):
    import sqlite3

    path = tmp_path / "rona.db"
    # Both toolbox.db.connect()/connect_if_exists() require the file to
    # already exist (see test_conversation_registry.py's identical
    # fixture) -- create it empty first, the way create_db.py's own
    # sqlite3.connect() call does in production.
    sqlite3.connect(str(path)).close()
    monkeypatch.setattr(toolbox_db, "DB_PATH", path)
    conversations.ensure_schema()
    history.ensure_schema()
    return path


def _user_msg(content: str, **extra) -> dict:
    return {"id": "u1", "role": "user", "content": content, "createdAt": 1, **extra}


def _assistant_msg(content: str, **extra) -> dict:
    return {"id": "a1", "role": "assistant", "content": content, "createdAt": 1, **extra}


# -- record_turn --------------------------------------------------------------


def test_record_turn_creates_conversation_with_derived_title(db_path):
    long_message = "hello there, how are you doing on this fine day today?"
    history.record_turn("t1", _user_msg(long_message), _assistant_msg("fine, thanks"))

    row = history.get("t1")

    assert row is not None
    assert row["title"] == long_message[:60]
    assert row["title_custom"] is False
    assert [m["content"] for m in row["messages"]] == [long_message, "fine, thanks"]


def test_record_turn_appends_to_existing_conversation(db_path):
    history.record_turn("t1", _user_msg("first"), _assistant_msg("ok"))
    history.record_turn("t1", _user_msg("second"), _assistant_msg("ok2"))

    row = history.get("t1")

    assert len(row["messages"]) == 4
    assert row["title"] == "first"


def test_record_turn_never_overwrites_a_custom_title(db_path):
    history.record_turn("t1", _user_msg("first"), _assistant_msg("ok"))
    history.rename("t1", "My chat")

    history.record_turn("t1", _user_msg("second"), _assistant_msg("ok2"))

    row = history.get("t1")
    assert row["title"] == "My chat"
    assert row["title_custom"] is True


def test_record_turn_is_a_noop_without_a_database(tmp_path, monkeypatch):
    monkeypatch.setattr(toolbox_db, "DB_PATH", tmp_path / "missing.db")

    history.record_turn("t1", _user_msg("hi"), _assistant_msg("hello"))

    assert history.get("t1") is None


# -- list_index -----------------------------------------------------------------


def test_list_index_reports_pinned_from_the_conversation_registry(db_path):
    history.record_turn("t1", _user_msg("a"), _assistant_msg("b"))
    conversations.touch("t1")
    conversations.set_pinned("t1", True)

    index = history.list_index()

    assert index[0]["thread_id"] == "t1"
    assert index[0]["pinned"] is True


def test_list_index_orders_by_updated_at_descending(db_path, monkeypatch):
    timestamps = iter([1000, 2000])
    monkeypatch.setattr(history, "_now_ms", lambda: next(timestamps))

    history.record_turn("older", _user_msg("a"), _assistant_msg("b"))
    history.record_turn("newer", _user_msg("a"), _assistant_msg("b"))

    index = history.list_index()

    assert [row["thread_id"] for row in index] == ["newer", "older"]


# -- rename / set_folder ---------------------------------------------------------


def test_rename_requires_an_existing_conversation(db_path):
    assert history.rename("missing", "New title") is False


def test_rename_rejects_a_blank_title(db_path):
    history.record_turn("t1", _user_msg("a"), _assistant_msg("b"))

    assert history.rename("t1", "   ") is False
    assert history.get("t1")["title_custom"] is False


def test_set_folder_moves_and_then_unfiles(db_path):
    history.record_turn("t1", _user_msg("a"), _assistant_msg("b"))
    folder = history.create_folder("Work")

    assert history.set_folder("t1", folder["id"]) is True
    assert history.get("t1")["folder_id"] == folder["id"]

    assert history.set_folder("t1", None) is True
    assert history.get("t1")["folder_id"] is None


# -- folder CRUD ------------------------------------------------------------------


def test_folder_crud(db_path):
    folder = history.create_folder("  Work  ")
    assert folder["name"] == "Work"
    assert folder["collapsed"] is False

    assert history.rename_folder(folder["id"], "Projects") is True
    assert history.set_folder_collapsed(folder["id"], True) is True

    [listed] = history.list_folders()
    assert listed["name"] == "Projects"
    assert listed["collapsed"] is True


def test_delete_folder_unfiles_but_keeps_its_conversations(db_path):
    history.record_turn("t1", _user_msg("a"), _assistant_msg("b"))
    folder = history.create_folder("Work")
    history.set_folder("t1", folder["id"])

    assert history.delete_folder(folder["id"]) is True

    assert history.list_folders() == []
    row = history.get("t1")
    assert row is not None
    assert row["folder_id"] is None


def test_delete_folder_returns_false_for_an_unknown_id(db_path):
    assert history.delete_folder("nope") is False


# -- delete / delete_all ----------------------------------------------------------


def test_delete_removes_the_conversation(db_path):
    history.record_turn("t1", _user_msg("a"), _assistant_msg("b"))

    history.delete("t1")

    assert history.get("t1") is None


def test_delete_all_skips_the_excluded_ids(db_path):
    history.record_turn("keep", _user_msg("a"), _assistant_msg("b"))
    history.record_turn("drop", _user_msg("a"), _assistant_msg("b"))

    deleted = history.delete_all(except_ids={"keep"})

    assert deleted == 1
    assert history.get("keep") is not None
    assert history.get("drop") is None


def test_delete_all_folders(db_path):
    history.create_folder("A")
    history.create_folder("B")

    assert history.delete_all_folders() == 2
    assert history.list_folders() == []


# -- export / import --------------------------------------------------------------


def test_export_all_matches_the_conversation_export_shape(db_path):
    history.record_turn("t1", _user_msg("a"), _assistant_msg("b"))
    conversations.set_pinned("t1", True)

    export = history.export_all()

    assert "exportedAt" in export
    [conv] = export["conversations"]
    assert conv["conversationId"] == "t1"
    assert conv["pinned"] is True
    assert len(conv["messages"]) == 2


def _legacy_conv(conversation_id: str, **overrides) -> dict:
    """One conversation as the pre-server frontend kept it in localStorage."""
    return {
        "conversationId": conversation_id,
        "title": "Legacy title",
        "titleCustom": False,
        "updatedAt": 1000,
        "pinned": False,
        "folderId": None,
        "messages": [],
        **overrides,
    }


def _pair(user: str, assistant: str, created_at: int) -> list[dict]:
    return [
        {"id": f"u-{created_at}", "role": "user", "content": user, "createdAt": created_at},
        {"id": f"a-{created_at}", "role": "assistant", "content": assistant, "createdAt": created_at},
    ]


def test_import_inserts_conversations_and_folders_the_server_lacks(db_path):
    result = history.import_conversations(
        conversations_in=[
            _legacy_conv(
                "imported",
                title="Imported chat",
                pinned=True,
                folderId="f1",
                messages=_pair("hi", "hello", 10),
            )
        ],
        folders_in=[{"id": "f1", "name": "Old folder", "createdAt": 1, "collapsed": False}],
    )

    assert result == {"conversations_imported": 1, "conversations_merged": 0, "folders_imported": 1}
    imported = history.get("imported")
    assert imported["title"] == "Imported chat"
    assert imported["pinned"] is True
    assert imported["folder_id"] == "f1"
    assert len(imported["messages"]) == 2
    [folder] = history.list_folders()
    assert folder["id"] == "f1"


def test_import_merges_turns_only_the_browser_had(db_path):
    # Started before the upgrade (only the browser saw turn 1), continued
    # after it (the server recorded turn 2, and so did the browser).
    history.record_turn("t1", *_pair("second question", "second answer", 200))

    result = history.import_conversations(
        conversations_in=[
            _legacy_conv(
                "t1",
                messages=[
                    *_pair("first question", "first answer", 100),
                    *_pair("second question", "second answer", 190),
                ],
            )
        ],
        folders_in=[],
    )

    assert result["conversations_merged"] == 1
    contents = [message["content"] for message in history.get("t1")["messages"]]
    assert contents == ["first question", "first answer", "second question", "second answer"]


def test_import_keeps_turns_only_the_server_has(db_path):
    history.record_turn("t1", *_pair("from the browser", "ok", 100))
    history.record_turn("t1", *_pair("from the phone, later", "ok too", 300))

    history.import_conversations(
        conversations_in=[_legacy_conv("t1", messages=_pair("from the browser", "ok", 90))],
        folders_in=[],
    )

    contents = [message["content"] for message in history.get("t1")["messages"]]
    assert contents == ["from the browser", "ok", "from the phone, later", "ok too"]


def test_import_does_not_collapse_a_message_genuinely_sent_twice(db_path):
    history.record_turn("t1", *_pair("evet", "tamam", 100))

    history.import_conversations(
        conversations_in=[
            _legacy_conv("t1", messages=[*_pair("evet", "tamam", 90), *_pair("evet", "tamam", 150)])
        ],
        folders_in=[],
    )

    assert len(history.get("t1")["messages"]) == 4


def test_import_is_a_no_op_the_second_time(db_path):
    payload = [_legacy_conv("t1", folderId="f1", messages=_pair("a", "b", 10))]
    folders = [{"id": "f1", "name": "F", "createdAt": 1, "collapsed": False}]
    history.import_conversations(conversations_in=payload, folders_in=folders)

    again = history.import_conversations(conversations_in=payload, folders_in=folders)

    assert again == {"conversations_imported": 0, "conversations_merged": 0, "folders_imported": 0}
    assert len(history.get("t1")["messages"]) == 2


def test_import_fills_a_missing_folder_but_never_moves_a_filed_one(db_path):
    history.record_turn("unfiled", *_pair("a", "b", 10))
    history.record_turn("filed", *_pair("a", "b", 10))
    history.set_folder("filed", "server-folder")

    history.import_conversations(
        conversations_in=[
            _legacy_conv("unfiled", folderId="browser-folder", messages=_pair("a", "b", 10)),
            _legacy_conv("filed", folderId="browser-folder", messages=_pair("a", "b", 10)),
        ],
        folders_in=[],
    )

    assert history.get("unfiled")["folder_id"] == "browser-folder"
    assert history.get("filed")["folder_id"] == "server-folder"


def test_import_applies_a_custom_title_only_over_an_auto_derived_one(db_path):
    history.record_turn("auto", *_pair("hello there", "hi", 10))
    history.record_turn("renamed", *_pair("hello there", "hi", 10))
    history.rename("renamed", "Chosen on the server")

    history.import_conversations(
        conversations_in=[
            _legacy_conv("auto", title="Chosen in the browser", titleCustom=True),
            _legacy_conv("renamed", title="Chosen in the browser", titleCustom=True),
        ],
        folders_in=[],
    )

    assert history.get("auto")["title"] == "Chosen in the browser"
    assert history.get("auto")["title_custom"] is True
    assert history.get("renamed")["title"] == "Chosen on the server"


def test_import_conversations_reenters_the_ttl_registry(db_path):
    history.import_conversations(conversations_in=[_legacy_conv("imported")], folders_in=[])

    registry_row = conversations.get("imported")

    assert registry_row is not None
    assert registry_row["pinned"] is False


def test_import_conversations_skips_entries_without_an_id(db_path):
    result = history.import_conversations(
        conversations_in=[{"title": "no id"}],
        folders_in=[{"name": "no id"}],
    )

    assert result == {"conversations_imported": 0, "conversations_merged": 0, "folders_imported": 0}


# -- TurnRecorder -----------------------------------------------------------------


class _FakeRun:
    def __init__(self) -> None:
        self.events: list[tuple[str, dict]] = []

    def publish(self, event_type: str, data: dict) -> None:
        self.events.append((event_type, data))


def test_turn_recorder_forwards_every_publish_to_the_wrapped_run():
    run = _FakeRun()
    recorder = history.TurnRecorder(run)

    recorder.publish("progress", {"type": "agent_start"})

    assert run.events == [("progress", {"type": "agent_start"})]


def test_turn_recorder_builds_steps_from_tool_start_and_tool_end():
    recorder = history.TurnRecorder(None)

    recorder.publish(
        "progress",
        {"type": "tool_start", "call_id": "c1", "name": "get_people", "args": {"a": 1}},
    )
    recorder.publish(
        "progress",
        {"type": "tool_end", "call_id": "c1", "status": "ok", "duration_ms": 42},
    )

    assert recorder.steps == [
        {
            "callId": "c1",
            "name": "get_people",
            "args": {"a": 1},
            "status": "ok",
            "durationMs": 42,
        }
    ]


def test_turn_recorder_ignores_non_progress_events():
    recorder = history.TurnRecorder(None)

    recorder.publish("done", {"status": "ok"})

    assert recorder.steps == []


# -- purge_expired also drops the chat history -------------------------------------


class _FakeCheckpointer:
    def __init__(self) -> None:
        self.deleted: list[str] = []

    async def adelete_thread(self, thread_id: str) -> None:
        self.deleted.append(thread_id)


def _backdate(db_path, thread_id: str, seconds_ago: float) -> None:
    import sqlite3

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


async def test_purge_expired_also_deletes_the_chat_history(db_path):
    history.record_turn("stale", _user_msg("a"), _assistant_msg("b"))
    conversations.touch("stale")
    _backdate(db_path, "stale", seconds_ago=1000)
    checkpointer = _FakeCheckpointer()

    purged = await threads.purge_expired(60, checkpointer, force=True)

    assert purged == 1
    assert checkpointer.deleted == ["stale"]
    assert history.get("stale") is None
