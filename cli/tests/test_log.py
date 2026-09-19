import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from types import SimpleNamespace

from rona_cli.backend_client import BackendUnavailable
from rona_cli.commands import log as log_cmd

from .helpers import make_root


def _write_backend_env(root, port, token="test-token"):
    (root / "backend" / ".env").write_text(
        f"AUTH_TOKEN={token}\nPORT={port}\nHOST=127.0.0.1\n", encoding="utf-8"
    )


def _args(root, **overrides):
    defaults = {
        "root": str(root),
        "json": False,
        "kind": "all",
        "status": None,
        "unread": False,
        "limit": 50,
        "id": None,
        "yes": False,
        "level": None,
        "grep": None,
    }
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


def test_list_prints_runs(tmp_path, fake_api, capsys):
    root = make_root(tmp_path)
    _write_backend_env(root, fake_api.port)
    fake_api.set_route(
        "GET",
        "/api/runs",
        200,
        {
            "runs": [
                {
                    "id": "r1",
                    "kind": "task",
                    "status": "completed",
                    "reported": True,
                    "started_at": "2026-01-01T00:00:00Z",
                    "task_name": "Water plants",
                }
            ]
        },
    )
    code = log_cmd._cmd_list(_args(root))
    assert code == 0
    assert "Water plants" in capsys.readouterr().out


def test_list_unread_sets_reported_false_query_param(tmp_path, fake_api):
    root = make_root(tmp_path)
    _write_backend_env(root, fake_api.port)
    fake_api.set_route("GET", "/api/runs", 200, {"runs": []})
    log_cmd._cmd_list(_args(root, unread=True))
    assert "reported=False" in fake_api.requests[0]["path"]


def test_show_prints_fields(tmp_path, fake_api, capsys):
    root = make_root(tmp_path)
    _write_backend_env(root, fake_api.port)
    fake_api.set_route("GET", "/api/runs/r1", 200, {"id": "r1", "status": "completed"})
    code = log_cmd._cmd_show(_args(root, id="r1"))
    assert code == 0
    assert "completed" in capsys.readouterr().out


def test_del_yes_flag_deletes(tmp_path, fake_api):
    root = make_root(tmp_path)
    _write_backend_env(root, fake_api.port)
    fake_api.set_route("DELETE", "/api/runs/r1", 200, {"deleted": True})
    code = log_cmd._cmd_del(_args(root, id="r1", yes=True))
    assert code == 0


def test_del_unreported_run_reports_409_message(tmp_path, fake_api, capsys):
    root = make_root(tmp_path)
    _write_backend_env(root, fake_api.port)
    fake_api.set_route("DELETE", "/api/runs/r1", 409, {"detail": "not reported"})
    code = log_cmd._cmd_del(_args(root, id="r1", yes=True))
    assert code == 1
    assert "bildirilmedi" in capsys.readouterr().err


def test_tail_local_filters_by_level_and_only_shows_new_lines(tmp_path, monkeypatch, capsys):
    log_path = tmp_path / "rona.log"
    log_path.write_text("2026 INFO old line\n", encoding="utf-8")

    calls = {"n": 0}

    def fake_sleep(_seconds):
        calls["n"] += 1
        if calls["n"] == 1:
            with log_path.open("a", encoding="utf-8") as handle:
                handle.write("2026 INFO new line\n2026 ERROR bad line\n")
        else:
            raise KeyboardInterrupt

    monkeypatch.setattr(log_cmd.time, "sleep", fake_sleep)
    code = log_cmd._tail_local(log_path, "INFO", None)
    assert code == 0
    out = capsys.readouterr().out
    assert "new line" in out
    assert "bad line" not in out
    assert "old line" not in out


def test_tail_local_missing_file_reports_error(tmp_path):
    code = log_cmd._tail_local(tmp_path / "missing.log", None, None)
    assert code == 1


def test_cmd_tail_falls_back_to_local_when_backend_unreachable(tmp_path, monkeypatch):
    root = make_root(tmp_path)
    (root / "backend" / ".env").write_text("AUTH_TOKEN=t\nPORT=1\n", encoding="utf-8")

    monkeypatch.setattr(
        log_cmd,
        "require_running",
        lambda client: (_ for _ in ()).throw(BackendUnavailable("down")),
    )
    calls = []
    monkeypatch.setattr(log_cmd, "_tail_local", lambda path, level, grep: calls.append(path) or 0)

    code = log_cmd._cmd_tail(_args(root))
    assert code == 0
    assert calls == [root / "backend" / "rona.log"]


def test_cmd_tail_uses_remote_when_backend_reachable(tmp_path, monkeypatch):
    root = make_root(tmp_path)
    (root / "backend" / ".env").write_text("AUTH_TOKEN=t\nPORT=1\n", encoding="utf-8")

    monkeypatch.setattr(log_cmd, "require_running", lambda client: None)
    calls = []
    monkeypatch.setattr(log_cmd, "_tail_remote", lambda client, level, grep: calls.append("remote") or 0)

    code = log_cmd._cmd_tail(_args(root))
    assert code == 0
    assert calls == ["remote"]


class _SSEHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.end_headers()
        self.wfile.write(b": ping\n\n")
        self.wfile.write(b'data: "line one"\n\n')
        self.wfile.write(b'data: "line two"\n\n')
        self.wfile.flush()

    def log_message(self, *args):
        pass


def test_tail_remote_reads_sse_data_lines(capsys):
    from rona_cli.http import Client

    httpd = HTTPServer(("127.0.0.1", 0), _SSEHandler)
    port = httpd.server_address[1]
    thread = threading.Thread(target=httpd.handle_request, daemon=True)
    thread.start()
    try:
        client = Client(base_url=f"http://127.0.0.1:{port}", token="t")
        code = log_cmd._tail_remote(client, None, None)
    finally:
        httpd.server_close()
    assert code == 0
    out = capsys.readouterr().out
    assert "line one" in out
    assert "line two" in out
