"""Tests for the web BFF's install/update/uninstall job runner.

Never touches a real backend venv or `toolbox.manager` -- `manager_command`
is monkeypatched (per-test) to point at a small throwaway Python script
instead, matching the one production choke point every manager subprocess
call goes through (see package_jobs.py's own docstring on why that
function exists). The script:

- optionally sleeps (``FAKE_MANAGER_SLEEP``), to hold a job "running" long
  enough for a second request to observe it;
- writes a ``[toolbox] ...`` progress line to stderr, the same prefix the
  real manager uses;
- echoes its own argv back in the JSON result (so tests can assert on
  exactly which flags a job was started with, and confirm ``--source`` is
  never among them);
- can be told to report failure (``FAKE_MANAGER_OK=0`` + an
  ``FAKE_MANAGER_ERROR`` message) or to bump a counter file
  (``FAKE_MANAGER_COUNTER``), for the /available cache test.
"""

import asyncio
import json
import sys
import time

import pytest
from fastapi.testclient import TestClient

import webui.server as server_module
from webui import host, package_jobs

FAKE_MANAGER_SCRIPT = """\
import json
import os
import sys
import time

counter_path = os.environ.get("FAKE_MANAGER_COUNTER")
if counter_path:
    try:
        with open(counter_path) as fh:
            count = int(fh.read().strip() or "0")
    except FileNotFoundError:
        count = 0
    count += 1
    with open(counter_path, "w") as fh:
        fh.write(str(count))

sleep_s = float(os.environ.get("FAKE_MANAGER_SLEEP", "0"))
if sleep_s:
    time.sleep(sleep_s)

print("[toolbox] pretending to work", file=sys.stderr, flush=True)

args = sys.argv[1:]
ok = os.environ.get("FAKE_MANAGER_OK", "1") != "0"
payload = {"ok": ok, "argv": args}
if not ok:
    payload["error"] = os.environ.get("FAKE_MANAGER_ERROR", "boom")
extra = os.environ.get("FAKE_MANAGER_EXTRA")
if extra:
    payload.update(json.loads(extra))
print(json.dumps(payload))
"""


@pytest.fixture(autouse=True)
def _reset_module_state(monkeypatch):
    # Every test starts as if no job had ever run and the catalog cache
    # were cold -- these are plain module globals (see package_jobs.py's
    # docstring: job state deliberately lives only in memory).
    monkeypatch.setattr(package_jobs, "_job", None)
    monkeypatch.setattr(package_jobs, "_available_cache", None)


@pytest.fixture
def client():
    return TestClient(server_module.create_app(), base_url="http://localhost")


@pytest.fixture
def fake_manager_script(tmp_path):
    script_path = tmp_path / "fake_manager.py"
    script_path.write_text(FAKE_MANAGER_SCRIPT, encoding="utf-8")
    return script_path


def _use_fake_manager(monkeypatch, script_path):
    monkeypatch.setattr(
        package_jobs,
        "manager_command",
        lambda *args: [sys.executable, str(script_path), *args],
    )


def _poll_job_until_done(client, timeout: float = 15.0) -> dict:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        job = client.get("/host/packages/job").json()["job"]
        if job is None or job["state"] != "running":
            return job
        time.sleep(0.1)
    pytest.fail("job never left the running state")


# -- GET /available -----------------------------------------------------------


def test_available_returns_manager_payload(client, fake_manager_script, monkeypatch):
    _use_fake_manager(monkeypatch, fake_manager_script)
    monkeypatch.setenv("FAKE_MANAGER_EXTRA", json.dumps({"packages": [{"id": "get_time"}]}))

    response = client.get("/host/packages/available")

    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    assert body["packages"] == [{"id": "get_time"}]
    assert body["argv"] == ["available"]
    assert "fetched_at" in body


def test_available_is_cached_until_refresh(client, fake_manager_script, monkeypatch, tmp_path):
    counter_path = tmp_path / "counter.txt"
    monkeypatch.setenv("FAKE_MANAGER_COUNTER", str(counter_path))
    _use_fake_manager(monkeypatch, fake_manager_script)

    first = client.get("/host/packages/available")
    second = client.get("/host/packages/available")
    assert first.status_code == 200
    assert second.status_code == 200
    assert counter_path.read_text().strip() == "1"

    refreshed = client.get("/host/packages/available", params={"refresh": 1})
    assert refreshed.status_code == 200
    assert counter_path.read_text().strip() == "2"


def test_available_manager_failure_is_502(client, fake_manager_script, monkeypatch):
    monkeypatch.setenv("FAKE_MANAGER_OK", "0")
    monkeypatch.setenv("FAKE_MANAGER_ERROR", "catalog unreachable")
    _use_fake_manager(monkeypatch, fake_manager_script)

    response = client.get("/host/packages/available")

    assert response.status_code == 502
    assert "catalog unreachable" in response.json()["detail"]


def test_missing_backend_python_is_503(client, monkeypatch):
    def _raise(*_args):
        raise package_jobs.ManagerUnavailable("D:/fake/backend/.venv/Scripts/python.exe")

    monkeypatch.setattr(package_jobs, "manager_command", _raise)

    response = client.get("/host/packages/available")

    assert response.status_code == 503
    assert "python.exe" in response.json()["detail"]


# -- GET /plan/{id} ------------------------------------------------------------


@pytest.mark.parametrize("bad_id", ["Bad", "a-b", "x" * 80])
def test_plan_rejects_invalid_id(client, bad_id):
    response = client.get(f"/host/packages/plan/{bad_id}")
    assert response.status_code == 400


def test_plan_refusal_is_409(client, fake_manager_script, monkeypatch):
    monkeypatch.setenv("FAKE_MANAGER_OK", "0")
    monkeypatch.setenv("FAKE_MANAGER_ERROR", "no catalog entry named 'nope'")
    _use_fake_manager(monkeypatch, fake_manager_script)

    response = client.get("/host/packages/plan/get_time")

    assert response.status_code == 409
    assert "nope" in response.json()["detail"]


# -- POST /install, /update, /uninstall + GET /job ----------------------------


def test_install_job_succeeds_with_log_and_flags(client, fake_manager_script, monkeypatch):
    _use_fake_manager(monkeypatch, fake_manager_script)

    response = client.post("/host/packages/install", json={"package_id": "get_time"})
    assert response.status_code == 202
    started = response.json()["job"]
    assert started["package_id"] == "get_time"
    assert started["action"] == "install"

    job = _poll_job_until_done(client)

    assert job["state"] == "succeeded"
    assert job["result"]["argv"] == [
        "install",
        "get_time",
        "--yes",
        "--defer-config",
        "--keep-on-health-failure",
    ]
    assert "--source" not in job["result"]["argv"]
    assert any("pretending to work" in line for line in job["log_lines"])


def test_second_job_while_running_is_409(client, fake_manager_script, monkeypatch):
    monkeypatch.setenv("FAKE_MANAGER_SLEEP", "2")
    _use_fake_manager(monkeypatch, fake_manager_script)

    first = client.post("/host/packages/install", json={"package_id": "get_time"})
    assert first.status_code == 202

    second = client.post("/host/packages/install", json={"package_id": "notes"})
    assert second.status_code == 409

    # Drain the first job so it doesn't outlive the test.
    _poll_job_until_done(client)


def test_failed_job_reports_error(client, fake_manager_script, monkeypatch):
    monkeypatch.setenv("FAKE_MANAGER_OK", "0")
    monkeypatch.setenv("FAKE_MANAGER_ERROR", "pip install failed")
    _use_fake_manager(monkeypatch, fake_manager_script)

    response = client.post("/host/packages/update", json={"package_id": "get_time"})
    assert response.status_code == 202

    job = _poll_job_until_done(client)

    assert job["state"] == "failed"
    assert "pip install failed" in job["error"]


def test_uninstall_passes_purge_never_force(client, fake_manager_script, monkeypatch):
    _use_fake_manager(monkeypatch, fake_manager_script)

    response = client.post(
        "/host/packages/uninstall", json={"package_id": "get_time", "purge": True}
    )
    assert response.status_code == 202

    job = _poll_job_until_done(client)

    assert job["result"]["argv"] == ["uninstall", "get_time", "--yes", "--purge"]
    assert "--force" not in job["result"]["argv"]


# -- CSRF guard (server-wide middleware, exercised through this router) -------


def test_non_json_post_is_415(client):
    response = client.post(
        "/host/packages/install",
        data="package_id=get_time",
        headers={"content-type": "application/x-www-form-urlencoded"},
    )
    assert response.status_code == 415


def test_cross_site_post_is_403(client):
    response = client.post(
        "/host/packages/install",
        json={"package_id": "get_time"},
        headers={"sec-fetch-site": "cross-site"},
    )
    assert response.status_code == 403


# -- host.py: backend venv python, not the BFF's own -------------------------


def test_spawn_backend_prefers_backend_venv_python(tmp_path, monkeypatch):
    fake_backend_dir = tmp_path / "backend"
    fake_backend_dir.mkdir()
    venv_bin = fake_backend_dir / ".venv" / ("Scripts" if sys.platform == "win32" else "bin")
    venv_bin.mkdir(parents=True)
    fake_python = venv_bin / ("python.exe" if sys.platform == "win32" else "python")
    fake_python.write_text("", encoding="utf-8")

    monkeypatch.setattr(host, "BACKEND_DIR", fake_backend_dir)
    monkeypatch.setattr(host, "SPAWN_LOG_PATH", tmp_path / "spawn.log")

    captured: dict = {}

    class FakePopen:
        def __init__(self, cmd, **kwargs):
            captured["cmd"] = cmd
            self.pid = 4321

        def poll(self):
            return None

    monkeypatch.setattr(host.subprocess, "Popen", FakePopen)

    async def _noop_sleep(*_args, **_kwargs):
        return None

    monkeypatch.setattr(host.asyncio, "sleep", _noop_sleep)

    try:
        result = asyncio.run(host._spawn_backend())
        assert result["ok"] is True
        assert captured["cmd"] == [str(fake_python), "run.py"]
    finally:
        host._backend_process = None
