import json
import sqlite3

import pytest

import create_db
from toolbox import db as toolbox_db
from trigger import executor, store

ACTION_ARGS = {"to": "a@example.com"}
REPORT_JSON = json.dumps(
    {
        "summary": "The mail was sent once to a@example.com.",
        "report": "Sent exactly one mail as approved.",
    }
)


@pytest.fixture
def db_path(tmp_path, monkeypatch):
    path = tmp_path / "rona.db"
    sqlite3.connect(str(path)).close()
    monkeypatch.setattr(toolbox_db, "DB_PATH", path)
    monkeypatch.setattr(create_db, "DB_PATH", path)
    create_db.create_database()
    return path


def _make_task(task_id="t1", **overrides):
    row = {
        "id": task_id,
        "name": "Mail task",
        "description": "send the mail",
        "status": "active",
        "is_recurring": False,
        "model": "flash",
        "cron_expression": None,
        "scheduled_at": "2026-01-01T00:00:00Z",
        "timezone": "UTC",
        "condition": None,
        "tool_name": "send_mail",
        "tool_params": ACTION_ARGS,
        "pre_approved_calls": None,
        "max_retries": 2,
        "retry_delay_seconds": 0,
        "timeout_minutes": 5,
    }
    row.update(overrides)
    store.create_task_row(row)
    return task_id


def _call(call_id, args=None):
    return {
        "id": call_id,
        "type": "function",
        "function": {
            "name": "send_mail",
            "arguments": json.dumps(ACTION_ARGS if args is None else args),
        },
    }


def _tool_round(*calls):
    return {"role": "assistant", "content": None, "tool_calls": list(calls)}


def _verdict(outcome, message="finished"):
    return {
        "role": "assistant",
        "content": json.dumps({"outcome": outcome, "message": message}),
    }


class Harness:
    def __init__(self, script):
        self.script = list(script)
        self.action_calls = 0
        self.worker_prompts = []

    async def chat(
        self, messages, conversation_id=None, tools=None, tier="flash", timeout=None, stream=False
    ):
        if messages[0]["content"].startswith("You are the reporting layer"):
            return {"role": "assistant", "content": REPORT_JSON}
        self.worker_prompts.append(messages[0]["content"])
        step = self.script.pop(0)
        if isinstance(step, Exception):
            raise step
        return step

    async def send_mail(self, **kwargs):
        self.action_calls += 1
        return "sent"


@pytest.fixture
def harness(monkeypatch, db_path):
    def install(script):
        h = Harness(script)
        monkeypatch.setattr(executor, "chat_completion", h.chat)
        monkeypatch.setattr(executor, "has_tool", lambda name: name == "send_mail")
        monkeypatch.setattr(executor, "get_tool", lambda name: h.send_mail)
        monkeypatch.setattr(executor, "get_tool_schemas", lambda names: [])
        monkeypatch.setattr(executor, "background_tool_names", lambda: set())
        monkeypatch.setattr(executor, "_load_worker_prompt", lambda: "worker prompt")
        return h

    return install


async def _run(task_id="t1", run_id="r1"):
    store.create_run(run_id, task_id)
    await executor._execute_occurrence(run_id, task_id)
    return store.get_run(run_id)


async def test_identical_calls_in_one_round_execute_once(harness):
    h = harness([_tool_round(_call("c1"), _call("c2")), _verdict("done")])
    _make_task()
    run = await _run()
    assert h.action_calls == 1
    assert run["status"] == "completed"
    assert store.action_done("r1") is True


async def test_second_call_gets_already_executed_message(harness):
    h = harness([])
    _make_task()
    store.create_run("r9", "t1")
    executed: set[int] = set()
    entry = {"tool_name": "send_mail", "tool_params": ACTION_ARGS}
    results = [
        await executor._execute_tool_call(_call(f"c{i}"), set(), [entry], entry, executed, "r9")
        for i in (1, 2)
    ]
    assert h.action_calls == 1
    assert json.loads(results[0][0]["content"])["status"] == "ok"
    assert json.loads(results[1][0]["content"]) == {
        "status": "error",
        "error": "This pre-approved action was already executed in this run; do not call it again.",
    }


async def test_action_ok_then_failed_verdict_is_done_not_retried(harness):
    h = harness([_tool_round(_call("c1")), _verdict("failed", "the mail bounced")])
    _make_task()
    run = await _run()
    assert h.action_calls == 1
    assert run["status"] == "completed"
    assert run["attempt"] == 1


async def test_action_ok_then_condition_not_met_is_done(harness):
    h = harness([_tool_round(_call("c1")), _verdict("condition_not_met")])
    _make_task()
    run = await _run()
    assert h.action_calls == 1
    assert run["status"] == "completed"


async def test_failed_action_is_still_retried(harness, monkeypatch):
    h = harness(
        [_tool_round(_call("c1")), _verdict("failed"), _tool_round(_call("c2")), _verdict("done")]
    )

    async def flaky(**kwargs):
        h.action_calls += 1
        if h.action_calls == 1:
            raise RuntimeError("smtp down")
        return "sent"

    monkeypatch.setattr(executor, "get_tool", lambda name: flaky)
    _make_task()
    run = await _run()
    assert h.action_calls == 2
    assert run["status"] == "completed"
    assert run["attempt"] == 2


async def test_persisted_action_done_blocks_action_in_later_attempt(harness):
    # Simulates a retry after an earlier attempt already ran the action: the
    # model tries to call it again and must be refused.
    h = harness([_tool_round(_call("c1")), _verdict("done")])
    _make_task()
    store.create_run("r1", "t1")
    store.mark_action_done("r1")
    await executor._execute_occurrence("r1", "t1")
    assert h.action_calls == 0
    assert executor.ACTION_ALREADY_DONE_NOTE in h.worker_prompts[0]
    assert store.get_run("r1")["status"] == "completed"


async def test_crash_after_action_does_not_rerun_it(harness):
    h = harness([_tool_round(_call("c1")), RuntimeError("boom")])
    _make_task()
    run = await _run()
    assert h.action_calls == 1
    assert run["status"] == "completed"


def test_action_done_roundtrip(db_path):
    _make_task()
    store.create_run("r1", "t1")
    assert store.action_done("r1") is False
    store.mark_action_done("r1")
    assert store.action_done("r1") is True
    assert store.action_done("missing") is False


def test_migration_adds_action_done_at_to_old_db(tmp_path, monkeypatch):
    path = tmp_path / "old.db"
    connection = sqlite3.connect(str(path))
    connection.execute(
        "CREATE TABLE task_runs (id TEXT PRIMARY KEY, task_id TEXT NOT NULL, "
        "status TEXT NOT NULL, attempt INTEGER NOT NULL DEFAULT 1, summary TEXT, "
        "report TEXT, error TEXT, started_at TEXT, finished_at TEXT, "
        "reported INTEGER NOT NULL DEFAULT 0, reported_at TEXT)"
    )
    connection.execute(
        "INSERT INTO task_runs (id, task_id, status) VALUES ('old', 't', 'completed')"
    )
    connection.execute("PRAGMA user_version = 3")
    connection.commit()
    connection.close()
    monkeypatch.setattr(toolbox_db, "DB_PATH", path)
    monkeypatch.setattr(create_db, "DB_PATH", path)

    create_db.create_database()

    connection = sqlite3.connect(str(path))
    try:
        columns = {row[1] for row in connection.execute("PRAGMA table_info(task_runs)")}
        assert "action_done_at" in columns
        assert connection.execute("SELECT action_done_at FROM task_runs").fetchone()[0] is None
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 6
    finally:
        connection.close()
