"""Direct (non-HTTP) tests for the small BFF fixes: read-only DB, supervisor
host mapping, _tail_lines, proxy helpers, and spawn log handle hygiene."""

import asyncio
import json
import sqlite3
import subprocess
from types import SimpleNamespace

import httpx
import pytest

from webui import db, host, proxy, supervisor

# ---- db --------------------------------------------------------------


def test_db_is_read_only_and_creates_no_wal(tmp_path, monkeypatch):
    path = tmp_path / "rona.db"
    setup = sqlite3.connect(path)
    setup.execute("CREATE TABLE t (id INTEGER)")
    setup.commit()
    setup.close()
    monkeypatch.setattr(db, "DB_PATH", path)

    connection = db.connect_if_exists()
    try:
        assert connection.execute("SELECT COUNT(*) FROM t").fetchone()[0] == 0
        with pytest.raises(sqlite3.OperationalError):
            connection.execute("INSERT INTO t VALUES (1)")
    finally:
        connection.close()
    assert not (tmp_path / "rona.db-wal").exists()


def test_db_missing_returns_none(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "nope.db")
    assert db.connect_if_exists() is None


# ---- supervisor ------------------------------------------------------


@pytest.mark.parametrize(
    ("bound", "expected"),
    [
        ("0.0.0.0", "127.0.0.1"),
        ("::", "127.0.0.1"),
        ("", "127.0.0.1"),
        ("127.0.0.1", "127.0.0.1"),
        ("localhost", "localhost"),
    ],
)
def test_probe_host_mapping(bound, expected):
    assert supervisor._probe_host(bound) == expected


def test_is_running_uses_loopback_and_localhost_host_header(monkeypatch):
    monkeypatch.setattr(supervisor.settings, "web_host", "0.0.0.0")
    monkeypatch.setattr(supervisor.settings, "web_port", 8765)
    seen = {}

    def fake_port_open(h, p, timeout=0.5):
        seen["port_host"] = h
        return True

    class FakeResponse:
        def json(self):
            return {"service": "rona-web", "pid": 1}

    def fake_get(url, **kwargs):
        seen["url"] = url
        seen["headers"] = kwargs.get("headers")
        return FakeResponse()

    monkeypatch.setattr(supervisor, "_port_open", fake_port_open)
    monkeypatch.setattr(httpx, "get", fake_get)
    assert supervisor.is_running() == {"service": "rona-web", "pid": 1}
    assert seen["port_host"] == "127.0.0.1"
    assert seen["url"] == "http://127.0.0.1:8765/host/healthz"
    assert seen["headers"] == {"Host": "localhost"}


# ---- _tail_lines -----------------------------------------------------


def test_tail_last_50_of_10000(tmp_path):
    path = tmp_path / "log.txt"
    path.write_text("".join(f"line {i}\n" for i in range(10_000)), encoding="utf-8")
    result = host._tail_lines(path, 50)
    assert result == [f"line {i}" for i in range(9_950, 10_000)]


def test_tail_short_file(tmp_path):
    path = tmp_path / "log.txt"
    path.write_text("a\nb\n", encoding="utf-8")
    assert host._tail_lines(path, 50) == ["a", "b"]


def test_tail_missing_and_empty(tmp_path):
    assert host._tail_lines(tmp_path / "none.txt", 5) == []
    empty = tmp_path / "empty.txt"
    empty.write_bytes(b"")
    assert host._tail_lines(empty, 5) == []


def test_tail_no_trailing_newline(tmp_path):
    path = tmp_path / "log.txt"
    path.write_text("one\ntwo\nthree", encoding="utf-8")
    assert host._tail_lines(path, 2) == ["two", "three"]


@pytest.mark.parametrize("block", [1, 2, 3, 5, 7, 16])
def test_tail_multibyte_across_blocks(tmp_path, block):
    path = tmp_path / "log.txt"
    lines = [f"çğş satır {i} İıÖü" for i in range(40)]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    assert host._tail_lines(path, 7, block_size=block) == lines[-7:]


# ---- proxy -----------------------------------------------------------


def test_error_response_is_valid_json():
    detail = 'bad "quote" and back\\slash'
    response = proxy._error_response(502, detail)
    assert response.status_code == 502
    assert json.loads(response.body) == {"detail": detail}


class _FakeRequest:
    def __init__(self, headers):
        self.headers = httpx.Headers(headers)


def test_request_headers_strip_and_inject(monkeypatch):
    monkeypatch.setattr(proxy.settings, "auth_token", "tok")
    result = proxy._request_headers(
        _FakeRequest(
            {
                "Cookie": "rona_session=secret",
                "Authorization": "Bearer user",
                "Host": "example.com",
                "Connection": "close",
                "X-Custom": "1",
            }
        )
    )
    assert "cookie" not in result
    assert "host" not in result
    assert "connection" not in result
    assert result["authorization"] == "Bearer tok"
    assert result["x-custom"] == "1"


@pytest.mark.parametrize(
    "path",
    [
        "/chat",
        "/api/connections/probe",
        "/api/packages/reload",
        "/api/packages/web_search/actions/verify",
        "/api/memory/consolidation/run",
    ],
)
def test_slow_paths_get_long_timeout(path):
    assert proxy._read_timeout(path) == 180.0


@pytest.mark.parametrize(
    "path",
    ["/chat/stream", "/api/connections", "/api/packages", "/api/packages/x/config", "/health"],
)
def test_other_paths_keep_default_timeout(path):
    assert proxy._read_timeout(path) == 45.0


# ---- spawn log handles ----------------------------------------------


class _PopenSpy:
    def __init__(self):
        self.stdout = None

    def __call__(self, *args, **kwargs):
        self.stdout = kwargs["stdout"]
        assert not self.stdout.closed

        class _Proc:
            pid = 1

            def poll(self):
                return None

        return _Proc()


def test_supervisor_start_closes_log_handle(tmp_path, monkeypatch):
    spy = _PopenSpy()
    monkeypatch.setattr(supervisor, "LOG_PATH", tmp_path / "web.log")
    monkeypatch.setattr(supervisor, "LOCK_PATH", tmp_path / "web.lock")
    monkeypatch.setattr(supervisor, "ROOT_DIR", tmp_path)
    monkeypatch.setattr(supervisor, "is_running", lambda: None)
    monkeypatch.setattr(supervisor, "STARTUP_TIMEOUT_SECONDS", 0)
    monkeypatch.setattr(subprocess, "Popen", spy)
    supervisor.start()
    assert spy.stdout is not None and spy.stdout.closed


def test_host_spawn_closes_log_handle(tmp_path, monkeypatch):
    spy = _PopenSpy()
    monkeypatch.setattr(host, "BACKEND_DIR", tmp_path)
    monkeypatch.setattr(host, "SPAWN_LOG_PATH", tmp_path / "spawn.log")
    monkeypatch.setattr(host, "_backend_process", None)
    monkeypatch.setattr(subprocess, "Popen", spy)

    async def no_sleep(_):
        return None

    monkeypatch.setattr(host.asyncio, "sleep", no_sleep)
    result = asyncio.run(host._spawn_backend())
    host._backend_process = None
    assert result["ok"] is True
    assert spy.stdout is not None and spy.stdout.closed


def test_probe_host_header_uses_first_allowed_host(monkeypatch):
    monkeypatch.setattr(supervisor.settings, "web_allowed_hosts", "*.example.com, panel.local ,x")
    assert supervisor._probe_host_header() == "panel.local"
    monkeypatch.setattr(supervisor.settings, "web_allowed_hosts", "")
    assert supervisor._probe_host_header() == "localhost"


def test_is_running_sends_allowed_host_header(monkeypatch):
    monkeypatch.setattr(supervisor.settings, "web_host", "127.0.0.1")
    monkeypatch.setattr(supervisor.settings, "web_allowed_hosts", "panel.local,localhost")
    seen = {}

    class FakeResponse:
        def json(self):
            return {"service": "rona-web", "pid": 1}

    monkeypatch.setattr(supervisor, "_port_open", lambda *a, **k: True)
    monkeypatch.setattr(
        httpx, "get", lambda url, **kw: seen.update(headers=kw["headers"]) or FakeResponse()
    )
    assert supervisor.is_running() is not None
    assert seen["headers"] == {"Host": "panel.local"}


# ---- proxy transport errors -----------------------------------------------


@pytest.mark.parametrize("error", [httpx.ReadError, httpx.RemoteProtocolError, httpx.WriteError])
def test_proxy_maps_transport_errors_to_502(monkeypatch, error):
    def handler(request):
        raise error("boom", request=request)

    monkeypatch.setattr(
        proxy,
        "_client",
        httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="http://backend"),
    )
    request = SimpleNamespace(
        method="GET", headers={}, query_params={}, body=lambda: _empty_body()
    )
    response = asyncio.run(proxy.proxy_request(request, "/api/x"))
    assert response.status_code == 502
    assert json.loads(response.body)["detail"]


async def _empty_body():
    return b""
