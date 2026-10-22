import asyncio
import subprocess
from types import SimpleNamespace

import pytest

from webui import host


def _fake_run(monkeypatch, *, returncode=0, stdout="loaded\n", raises=None):
    def _run(cmd, **kwargs):
        if raises is not None:
            raise raises
        return SimpleNamespace(returncode=returncode, stdout=stdout, stderr="")

    monkeypatch.setattr(host.subprocess, "run", _run)
    monkeypatch.setattr(host.shutil, "which", lambda _: "/usr/bin/systemctl")
    monkeypatch.setattr(host.sys, "platform", "linux")


def test_unavailable_without_systemctl(monkeypatch):
    _fake_run(monkeypatch)
    monkeypatch.setattr(host.shutil, "which", lambda _: None)
    assert host._systemd_unit_available() is False


def test_unavailable_on_windows_and_macos(monkeypatch):
    _fake_run(monkeypatch)
    for platform in ("win32", "darwin"):
        monkeypatch.setattr(host.sys, "platform", platform)
        assert host._systemd_unit_available() is False


def test_available_when_loaded(monkeypatch):
    _fake_run(monkeypatch)
    assert host._systemd_unit_available() is True


def test_unavailable_when_not_found(monkeypatch):
    _fake_run(monkeypatch, stdout="not-found\n")
    assert host._systemd_unit_available() is False


def test_unavailable_on_bus_error(monkeypatch):
    _fake_run(monkeypatch, returncode=1, stdout="")
    assert host._systemd_unit_available() is False


def test_unavailable_on_timeout(monkeypatch):
    _fake_run(monkeypatch, raises=subprocess.TimeoutExpired(cmd="systemctl", timeout=10))
    assert host._systemd_unit_available() is False


@pytest.fixture
def direct_path(monkeypatch):
    calls = {"systemctl": [], "spawn": 0, "kill": 0}
    monkeypatch.setattr(host, "_systemd_unit_available", lambda: False)
    monkeypatch.setattr(
        host, "_run_systemctl", lambda a: calls["systemctl"].append(a) or {"ok": True}
    )

    async def _spawn():
        calls["spawn"] += 1
        return {"ok": True}

    def _kill():
        calls["kill"] += 1
        return {"ok": True}

    async def _nosleep(_):
        return None

    monkeypatch.setattr(host, "_spawn_backend", _spawn)
    monkeypatch.setattr(host, "_kill_backend", _kill)
    monkeypatch.setattr(host.asyncio, "sleep", _nosleep)
    monkeypatch.setattr(host, "_last_restart_at", 0.0)
    monkeypatch.setattr(host, "RESTART_MIN_INTERVAL_SECONDS", 0)
    return calls


_REQUEST = SimpleNamespace(client=SimpleNamespace(host="test"))


def test_start_stop_restart_use_direct_path_without_unit(direct_path):
    asyncio.run(host.server_start(_REQUEST))
    asyncio.run(host.server_stop(_REQUEST))
    asyncio.run(host.server_restart(_REQUEST))
    assert direct_path["systemctl"] == []
    assert direct_path["spawn"] == 2
    assert direct_path["kill"] == 2


def test_start_uses_systemctl_when_unit_loaded(direct_path, monkeypatch):
    monkeypatch.setattr(host, "_systemd_unit_available", lambda: True)
    asyncio.run(host.server_start(_REQUEST))
    assert direct_path["systemctl"] == ["start"]
    assert direct_path["spawn"] == 0
