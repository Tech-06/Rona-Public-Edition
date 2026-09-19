import sqlite3
import time

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import app.dashboard as dashboard_module
import create_db
from subagents import store as subagent_store
from toolbox import db as toolbox_db
from trigger import store as trigger_store

TASK_DEFAULTS = {
    "description": "a test task",
    "is_recurring": False,
    "model": "flash",
    "cron_expression": None,
    "scheduled_at": "2026-01-01T00:00:00Z",
    "timezone": "UTC",
    "condition": None,
    "tool_name": None,
    "tool_params": None,
    "pre_approved_calls": None,
    "max_retries": 2,
    "retry_delay_seconds": 300,
    "timeout_minutes": 15,
}


@pytest.fixture
def client(tmp_path, monkeypatch):
    db_path = tmp_path / "rona.db"
    sqlite3.connect(str(db_path)).close()
    monkeypatch.setattr(toolbox_db, "DB_PATH", db_path)
    monkeypatch.setattr(create_db, "DB_PATH", db_path)
    create_db.create_database()

    test_app = FastAPI()
    test_app.include_router(dashboard_module.router)
    return TestClient(test_app), db_path


def _make_task(task_id: str, status: str = "active") -> None:
    trigger_store.create_task_row({"id": task_id, "name": f"Task {task_id}", "status": status, **TASK_DEFAULTS})


def _make_task_run(task_id: str, run_id: str, *, outcome: str = "completed", reported: bool = False) -> None:
    trigger_store.create_run(run_id, task_id)
    if outcome == "completed":
        trigger_store.complete_run(run_id, "done", "full report")
    elif outcome == "failed":
        trigger_store.fail_run(run_id, "boom")
    if reported:
        trigger_store.mark_run_reported(run_id)


def _make_subagent_run(run_id: str, *, outcome: str = "completed", reported: bool = False) -> None:
    subagent_store.create_run(run_id, "do something", "flash")
    if outcome == "completed":
        subagent_store.complete_run(run_id, "done", "full report")
    elif outcome == "failed":
        subagent_store.fail_run(run_id, "boom")
    if reported:
        subagent_store.mark_reported(run_id)


def test_list_runs_merges_both_kinds(client):
    test_client, _ = client
    _make_task("t1")
    _make_task_run("t1", "run-task-1")
    _make_subagent_run("run-sub-1")

    response = test_client.get("/api/runs")
    assert response.status_code == 200
    runs = response.json()["runs"]
    kinds = {run["kind"] for run in runs}
    assert kinds == {"task", "subagent"}
    assert len(runs) == 2


def test_list_runs_filters_by_kind(client):
    test_client, _ = client
    _make_task("t1")
    _make_task_run("t1", "run-task-1")
    _make_subagent_run("run-sub-1")

    task_only = test_client.get("/api/runs", params={"kind": "task"}).json()["runs"]
    assert len(task_only) == 1
    assert task_only[0]["kind"] == "task"

    subagent_only = test_client.get("/api/runs", params={"kind": "subagent"}).json()["runs"]
    assert len(subagent_only) == 1
    assert subagent_only[0]["kind"] == "subagent"


def test_list_runs_rejects_invalid_kind(client):
    test_client, _ = client
    response = test_client.get("/api/runs", params={"kind": "bogus"})
    assert response.status_code == 400


def test_list_runs_filters_by_status(client):
    test_client, _ = client
    _make_task("t1")
    _make_task_run("t1", "run-ok", outcome="completed")
    _make_task_run("t1", "run-bad", outcome="failed")

    failed_only = test_client.get("/api/runs", params={"status": "failed"}).json()["runs"]
    assert len(failed_only) == 1
    assert failed_only[0]["id"] == "run-bad"


def test_list_runs_filters_by_reported(client):
    test_client, _ = client
    _make_task("t1")
    _make_task_run("t1", "run-seen", reported=True)
    _make_task_run("t1", "run-unseen", reported=False)

    unreported = test_client.get("/api/runs", params={"reported": False}).json()["runs"]
    assert {run["id"] for run in unreported} == {"run-unseen"}

    reported = test_client.get("/api/runs", params={"reported": True}).json()["runs"]
    assert {run["id"] for run in reported} == {"run-seen"}


def test_list_runs_sorted_newest_first(client):
    test_client, _ = client
    _make_task("t1")
    _make_task_run("t1", "run-older")
    time.sleep(1.05)  # started_at has 1-second resolution
    _make_task_run("t1", "run-newer")

    runs = test_client.get("/api/runs").json()["runs"]
    assert [run["id"] for run in runs] == ["run-newer", "run-older"]


def test_get_run_detail_finds_task_run(client):
    test_client, _ = client
    _make_task("t1")
    _make_task_run("t1", "run-1")
    response = test_client.get("/api/runs/run-1")
    assert response.status_code == 200
    assert response.json()["kind"] == "task"


def test_get_run_detail_finds_subagent_run(client):
    test_client, _ = client
    _make_subagent_run("run-1")
    response = test_client.get("/api/runs/run-1")
    assert response.status_code == 200
    assert response.json()["kind"] == "subagent"


def test_get_run_detail_missing_returns_404(client):
    test_client, _ = client
    response = test_client.get("/api/runs/does-not-exist")
    assert response.status_code == 404


def test_delete_unreported_run_returns_409(client):
    test_client, _ = client
    _make_task("t1")
    _make_task_run("t1", "run-1", reported=False)
    response = test_client.delete("/api/runs/run-1")
    assert response.status_code == 409
    assert test_client.get("/api/runs/run-1").status_code == 200


def test_delete_reported_task_run_succeeds(client):
    test_client, _ = client
    _make_task("t1")
    _make_task_run("t1", "run-1", reported=True)
    response = test_client.delete("/api/runs/run-1")
    assert response.status_code == 200
    assert response.json() == {"deleted": True}
    assert test_client.get("/api/runs/run-1").status_code == 404


def test_delete_reported_subagent_run_succeeds(client):
    test_client, _ = client
    _make_subagent_run("run-1", reported=True)
    response = test_client.delete("/api/runs/run-1")
    assert response.status_code == 200
    assert test_client.get("/api/runs/run-1").status_code == 404


def test_delete_unknown_run_returns_404(client):
    test_client, _ = client
    response = test_client.delete("/api/runs/does-not-exist")
    assert response.status_code == 404
