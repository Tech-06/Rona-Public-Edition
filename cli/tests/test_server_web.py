import json
import os
import socket
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from types import SimpleNamespace
from typing import ClassVar

import pytest

from rona_cli import procutil
from rona_cli.commands import server, web
from rona_cli.paths import RonaPaths


def _make_root(tmp_path):
    root = tmp_path / "rona-checkout"
    (root / "backend").mkdir(parents=True)
    (root / "web-client").mkdir(parents=True)
    return root


def _add_fake_backend_venv(root) -> None:
    """`_start`'s spawn fallback locates an interpreter via
    `RonaPaths.backend_python()` before ever calling the (monkeypatched)
    spawn function -- give it a placeholder file to find."""
    venv_dir = root / "backend" / ".venv"
    python_path = (
        venv_dir / "Scripts" / "python.exe" if os.name == "nt" else venv_dir / "bin" / "python"
    )
    python_path.parent.mkdir(parents=True)
    python_path.write_text("", encoding="utf-8")


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


class _FakeApiHandler(BaseHTTPRequestHandler):
    routes: ClassVar[dict[str, dict]] = {}

    def _respond(self, path: str) -> None:
        payload = self.routes.get(path)
        if payload is None:
            self.send_response(404)
            self.end_headers()
            return
        body = json.dumps(payload).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        self._respond(self.path)

    def log_message(self, *args):
        pass  # keep test output quiet


@pytest.fixture
def fake_server():
    servers: list[ThreadingHTTPServer] = []

    def _start(routes: dict[str, dict]) -> int:
        handler_cls = type("Handler", (_FakeApiHandler,), {"routes": routes})
        httpd = ThreadingHTTPServer(("127.0.0.1", 0), handler_cls)
        port = httpd.server_address[1]
        thread = threading.Thread(target=httpd.serve_forever, daemon=True)
        thread.start()
        servers.append(httpd)
        return port

    yield _start

    for httpd in servers:
        httpd.shutdown()
        httpd.server_close()


def test_server_describe_reports_running_when_backend_is_up(tmp_path, fake_server):
    port = fake_server(
        {
            "/api/status": {
                "app": "Rona",
                "uptime_seconds": 12.3,
                "flash_model": "test-model",
                "pro_configured": False,
                "scheduler_running": True,
            }
        }
    )
    root = _make_root(tmp_path)
    (root / "backend" / ".env").write_text(
        f"AUTH_TOKEN=testtoken\nPORT={port}\nHOST=127.0.0.1\n", encoding="utf-8"
    )
    data = server.describe(RonaPaths(root))
    assert data["running"] is True
    assert data["flash_model"] == "test-model"


def test_server_describe_reports_not_running_when_port_closed(tmp_path):
    root = _make_root(tmp_path)
    closed_port = _free_port()
    (root / "backend" / ".env").write_text(
        f"AUTH_TOKEN=testtoken\nPORT={closed_port}\nHOST=127.0.0.1\n", encoding="utf-8"
    )
    data = server.describe(RonaPaths(root))
    assert data["running"] is False
    assert "detail" in data


def test_server_describe_without_auth_token_reports_not_running(tmp_path):
    root = _make_root(tmp_path)
    (root / "backend" / ".env").write_text("PORT=8000\n", encoding="utf-8")
    data = server.describe(RonaPaths(root))
    assert data["running"] is False
    assert "AUTH_TOKEN" in data["detail"]


def test_web_describe_reports_running_when_dashboard_is_up(tmp_path, fake_server):
    port = fake_server({"/host/healthz": {"service": "rona-web", "pid": 4242, "uptime_seconds": 5}})
    root = _make_root(tmp_path)
    (root / "web-client" / ".env").write_text(
        f"WEB_HOST=127.0.0.1\nWEB_PORT={port}\n", encoding="utf-8"
    )
    data = web.describe(RonaPaths(root))
    assert data["running"] is True
    assert data["pid"] == 4242


def _web_status(tmp_path, fake_server, capsys, *, frontend_stale: bool) -> str:
    import argparse

    port = fake_server(
        {
            "/host/healthz": {
                "service": "rona-web",
                "pid": 1,
                "uptime_seconds": 5,
                "frontend_stale": frontend_stale,
            }
        }
    )
    root = _make_root(tmp_path)
    (root / "web-client" / ".env").write_text(
        f"WEB_HOST=127.0.0.1\nWEB_PORT={port}\n", encoding="utf-8"
    )
    web._cmd_status(argparse.Namespace(root=str(root), json=False))
    return capsys.readouterr().out


def test_web_status_warns_when_the_frontend_build_is_stale(tmp_path, fake_server, capsys):
    output = _web_status(tmp_path, fake_server, capsys, frontend_stale=True)
    assert "rona web build" in output


def test_web_status_is_quiet_when_the_frontend_build_is_current(tmp_path, fake_server, capsys):
    output = _web_status(tmp_path, fake_server, capsys, frontend_stale=False)
    assert "rona web build" not in output


# -- rona web build ---------------------------------------------------------------


def _build_frontend_dir(root, *, lockfile: bool):
    frontend_dir = root / "web-client" / "frontend"
    frontend_dir.mkdir(parents=True)
    if lockfile:
        (frontend_dir / "package-lock.json").write_text("{}", encoding="utf-8")
    return frontend_dir


def test_build_uses_npm_ci_when_a_lockfile_exists(tmp_path, monkeypatch):
    root = _make_root(tmp_path)
    frontend_dir = _build_frontend_dir(root, lockfile=True)
    monkeypatch.setattr(web.shutil, "which", lambda _name: "/usr/bin/npm")
    calls = []

    def _fake_run(cmd, cwd, check, shell):
        calls.append((cmd, cwd))
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(web.subprocess, "run", _fake_run)

    code = web._cmd_build(SimpleNamespace(root=str(root), json=False))

    assert code == 0
    assert [cmd for cmd, _ in calls] == [["/usr/bin/npm", "ci"], ["/usr/bin/npm", "run", "build"]]
    assert all(cwd == frontend_dir for _, cwd in calls)


def test_build_uses_npm_install_without_a_lockfile(tmp_path, monkeypatch):
    root = _make_root(tmp_path)
    _build_frontend_dir(root, lockfile=False)
    monkeypatch.setattr(web.shutil, "which", lambda _name: "/usr/bin/npm")
    calls = []
    monkeypatch.setattr(
        web.subprocess,
        "run",
        lambda cmd, cwd, check, shell: calls.append(cmd) or SimpleNamespace(returncode=0),
    )

    code = web._cmd_build(SimpleNamespace(root=str(root), json=False))

    assert code == 0
    assert calls[0] == ["/usr/bin/npm", "install"]


def test_build_stops_after_a_failed_install(tmp_path, monkeypatch):
    root = _make_root(tmp_path)
    _build_frontend_dir(root, lockfile=True)
    monkeypatch.setattr(web.shutil, "which", lambda _name: "/usr/bin/npm")
    calls = []

    def _fake_run(cmd, cwd, check, shell):
        calls.append(cmd)
        return SimpleNamespace(returncode=1)

    monkeypatch.setattr(web.subprocess, "run", _fake_run)

    code = web._cmd_build(SimpleNamespace(root=str(root), json=False))

    assert code == 1
    assert len(calls) == 1  # never reached "npm run build"


def test_build_fails_without_npm(tmp_path, monkeypatch):
    root = _make_root(tmp_path)
    _build_frontend_dir(root, lockfile=True)
    monkeypatch.setattr(web.shutil, "which", lambda _name: None)
    calls = []
    monkeypatch.setattr(web.subprocess, "run", lambda *a, **k: calls.append(1))

    code = web._cmd_build(SimpleNamespace(root=str(root), json=False))

    assert code == 1
    assert calls == []


def test_build_json_mode_prints_ok_on_success(tmp_path, monkeypatch, capsys):
    root = _make_root(tmp_path)
    _build_frontend_dir(root, lockfile=True)
    monkeypatch.setattr(web.shutil, "which", lambda _name: "/usr/bin/npm")
    monkeypatch.setattr(web.subprocess, "run", lambda *a, **k: SimpleNamespace(returncode=0))

    code = web._cmd_build(SimpleNamespace(root=str(root), json=True))

    assert code == 0
    assert json.loads(capsys.readouterr().out) == {"ok": True}


def test_web_describe_reports_not_running_when_closed(tmp_path):
    root = _make_root(tmp_path)
    closed_port = _free_port()
    (root / "web-client" / ".env").write_text(
        f"WEB_HOST=127.0.0.1\nWEB_PORT={closed_port}\n", encoding="utf-8"
    )
    data = web.describe(RonaPaths(root))
    assert data["running"] is False


def test_systemctl_available_false_on_windows(monkeypatch):
    monkeypatch.setattr(server.shutil, "which", lambda _: "/usr/bin/systemctl")
    monkeypatch.setattr(server.os, "name", "nt")
    assert server._systemctl_available() is False


def test_systemctl_available_true_when_present_on_posix(monkeypatch):
    monkeypatch.setattr(server.shutil, "which", lambda _: "/usr/bin/systemctl")
    monkeypatch.setattr(server.os, "name", "posix")
    assert server._systemctl_available() is True


def test_systemctl_available_false_when_not_on_path(monkeypatch):
    monkeypatch.setattr(server.shutil, "which", lambda _: None)
    monkeypatch.setattr(server.os, "name", "posix")
    assert server._systemctl_available() is False


def test_start_prefers_systemd_when_available(tmp_path, monkeypatch):
    # The initial health probe must fail (nothing listening yet) so `_start`
    # actually reaches the systemd branch instead of short-circuiting on
    # "already running". The fake `_run_systemctl` then brings a server up
    # on that same port, simulating what a real `systemctl start` would do.
    root = _make_root(tmp_path)
    port = _free_port()
    (root / "backend" / ".env").write_text(
        f"AUTH_TOKEN=testtoken\nPORT={port}\nHOST=127.0.0.1\n", encoding="utf-8"
    )
    monkeypatch.setattr(server, "_systemctl_available", lambda: True)
    monkeypatch.setattr(server, "START_TIMEOUT_SECONDS", 2)
    monkeypatch.setattr(server, "POLL_INTERVAL_SECONDS", 0.05)

    calls: list[str] = []
    httpd_holder: dict[str, ThreadingHTTPServer] = {}

    def _fake_run_systemctl(action):
        calls.append(action)
        handler_cls = type(
            "Handler", (_FakeApiHandler,), {"routes": {"/health": {"status": "ok"}}}
        )
        httpd = ThreadingHTTPServer(("127.0.0.1", port), handler_cls)
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
        httpd_holder["server"] = httpd
        return True, "ok"

    monkeypatch.setattr(server, "_run_systemctl", _fake_run_systemctl)

    try:
        ok, _detail = server._start(RonaPaths(root))
    finally:
        httpd = httpd_holder.get("server")
        if httpd is not None:
            httpd.shutdown()
            httpd.server_close()

    assert ok is True
    assert calls == ["start"]


def test_start_falls_back_to_spawn_when_no_systemd(tmp_path, monkeypatch):
    root = _make_root(tmp_path)
    _add_fake_backend_venv(root)
    port = _free_port()
    (root / "backend" / ".env").write_text(
        f"AUTH_TOKEN=testtoken\nPORT={port}\nHOST=127.0.0.1\n", encoding="utf-8"
    )
    monkeypatch.setattr(server, "_systemctl_available", lambda: False)
    monkeypatch.setattr(server, "EARLY_EXIT_CHECK_SECONDS", 0)
    monkeypatch.setattr(server, "START_TIMEOUT_SECONDS", 2)
    monkeypatch.setattr(server, "POLL_INTERVAL_SECONDS", 0.05)

    class _FakeProc:
        pid = 999999
        returncode = None

        def poll(self):
            return None  # still "running"

    spawn_calls = []
    httpd_holder: dict[str, ThreadingHTTPServer] = {}

    def _fake_spawn(cmd, cwd, log_path):
        spawn_calls.append((cmd, cwd))
        handler_cls = type(
            "Handler", (_FakeApiHandler,), {"routes": {"/health": {"status": "ok"}}}
        )
        httpd = ThreadingHTTPServer(("127.0.0.1", port), handler_cls)
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
        httpd_holder["server"] = httpd
        return _FakeProc()

    monkeypatch.setattr(server.procutil, "spawn_detached", _fake_spawn)

    paths = RonaPaths(root)
    try:
        ok, _detail = server._start(paths)
    finally:
        httpd = httpd_holder.get("server")
        if httpd is not None:
            httpd.shutdown()
            httpd.server_close()

    assert ok is True
    assert len(spawn_calls) == 1
    assert paths.backend_pid.read_text(encoding="utf-8") == "999999"


def test_stop_reports_already_stopped_when_nothing_listening(tmp_path):
    root = _make_root(tmp_path)
    closed_port = _free_port()
    (root / "backend" / ".env").write_text(
        f"AUTH_TOKEN=testtoken\nPORT={closed_port}\nHOST=127.0.0.1\n", encoding="utf-8"
    )
    ok, detail = server._stop(RonaPaths(root))
    assert ok is True
    assert "zaten" in detail


def test_pid_file_lifecycle(tmp_path):
    pid_path = tmp_path / "rona.pid"
    assert procutil.read_pid_file(pid_path) is None
    procutil.write_pid_file(pid_path, 12345)
    assert procutil.read_pid_file(pid_path) == 12345
    procutil.clear_pid_file(pid_path)
    assert procutil.read_pid_file(pid_path) is None
    procutil.clear_pid_file(pid_path)  # noop, must not raise


def test_port_open_true_for_listening_socket():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        sock.listen(1)
        port = sock.getsockname()[1]
        assert procutil.port_open("127.0.0.1", port) is True


def test_port_open_false_for_closed_port():
    port = _free_port()
    assert procutil.port_open("127.0.0.1", port) is False


def test_find_pid_by_port_returns_none_when_nothing_listening():
    port = _free_port()
    assert procutil.find_pid_by_port("127.0.0.1", port) is None


def test_pid_alive_false_for_bogus_pid():
    # A pid this large is never a real process on any platform.
    assert procutil.pid_alive(2**30) is False
