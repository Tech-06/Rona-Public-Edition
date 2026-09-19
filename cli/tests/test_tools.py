import json
import os
from types import SimpleNamespace

from rona_cli.commands import tools

from .helpers import make_root


def _add_fake_backend_venv(root) -> None:
    venv_dir = root / "backend" / ".venv"
    python_path = (
        venv_dir / "Scripts" / "python.exe" if os.name == "nt" else venv_dir / "bin" / "python"
    )
    python_path.parent.mkdir(parents=True)
    python_path.write_text("", encoding="utf-8")


def _args(root, **overrides):
    defaults = {
        "root": str(root),
        "json": False,
        "source": None,
        "set": None,
        "yes": False,
        "keep_on_health_failure": False,
        "force": False,
        "package_id": "get_time",
    }
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


class _FakeCompleted:
    def __init__(self, stdout="", stderr="", returncode=0):
        self.stdout = stdout
        self.stderr = stderr
        self.returncode = returncode


def test_list_parses_manager_json_and_prints_table(tmp_path, monkeypatch, capsys):
    root = make_root(tmp_path)
    _add_fake_backend_venv(root)
    calls = []

    def _fake_run(cmd, cwd, capture_output, text, check):
        calls.append(cmd)
        payload = {"ok": True, "packages": [{"id": "get_time", "version": "1.0.0", "name": "Get Time"}]}
        return _FakeCompleted(stdout=json.dumps(payload) + "\n")

    monkeypatch.setattr(tools.subprocess, "run", _fake_run)
    code = tools._cmd_list(_args(root))
    assert code == 0
    assert "get_time" in capsys.readouterr().out
    # --json must come before the subcommand -- that's how manager.py's own
    # argparse expects it (a top-level flag, not per-subcommand).
    assert calls[0].index("--json") < calls[0].index("installed")


def test_list_empty_shows_none_installed(tmp_path, monkeypatch, capsys):
    root = make_root(tmp_path)
    _add_fake_backend_venv(root)
    monkeypatch.setattr(
        tools.subprocess,
        "run",
        lambda *a, **k: _FakeCompleted(stdout=json.dumps({"ok": True, "packages": []}) + "\n"),
    )
    code = tools._cmd_list(_args(root))
    assert code == 0
    assert "yok" in capsys.readouterr().out.lower()


def test_list_json_mode_passes_through_manager_payload(tmp_path, monkeypatch, capsys):
    root = make_root(tmp_path)
    _add_fake_backend_venv(root)
    payload = {"ok": True, "packages": [{"id": "x", "version": "1", "name": "X"}]}
    monkeypatch.setattr(
        tools.subprocess, "run", lambda *a, **k: _FakeCompleted(stdout=json.dumps(payload) + "\n")
    )
    code = tools._cmd_list(_args(root, json=True))
    assert code == 0
    assert json.loads(capsys.readouterr().out) == payload


def test_available_forwards_source_flag(tmp_path, monkeypatch):
    root = make_root(tmp_path)
    _add_fake_backend_venv(root)
    calls = []

    def _fake_run(cmd, cwd, capture_output, text, check):
        calls.append(cmd)
        return _FakeCompleted(stdout=json.dumps({"ok": True, "packages": []}) + "\n")

    monkeypatch.setattr(tools.subprocess, "run", _fake_run)
    tools._cmd_available(_args(root, source="local:/tmp/catalog"))
    assert "--source" in calls[0]
    assert "local:/tmp/catalog" in calls[0]


def test_available_no_packages_shows_catalog_empty(tmp_path, monkeypatch, capsys):
    root = make_root(tmp_path)
    _add_fake_backend_venv(root)
    monkeypatch.setattr(
        tools.subprocess,
        "run",
        lambda *a, **k: _FakeCompleted(stdout=json.dumps({"ok": True, "packages": []}) + "\n"),
    )
    code = tools._cmd_available(_args(root))
    assert code == 0
    assert capsys.readouterr().out.strip()


def test_verify_ok_prints_detail_and_returns_zero(tmp_path, monkeypatch, capsys):
    root = make_root(tmp_path)
    _add_fake_backend_venv(root)
    monkeypatch.setattr(
        tools.subprocess,
        "run",
        lambda *a, **k: _FakeCompleted(stdout=json.dumps({"ok": True, "detail": "ok"}) + "\n"),
    )
    code = tools._cmd_verify(_args(root, package_id="get_time"))
    assert code == 0
    assert "ok" in capsys.readouterr().out


def test_verify_failure_returns_nonzero(tmp_path, monkeypatch):
    root = make_root(tmp_path)
    _add_fake_backend_venv(root)
    monkeypatch.setattr(
        tools.subprocess,
        "run",
        lambda *a, **k: _FakeCompleted(stdout=json.dumps({"ok": False, "detail": "broken"}) + "\n"),
    )
    code = tools._cmd_verify(_args(root, package_id="get_time"))
    assert code == 1


def test_install_inherits_stdio_and_forwards_flags(tmp_path, monkeypatch):
    root = make_root(tmp_path)
    _add_fake_backend_venv(root)
    calls = []

    def _fake_run(cmd, cwd, check):
        calls.append(cmd)
        return _FakeCompleted(returncode=0)

    monkeypatch.setattr(tools.subprocess, "run", _fake_run)
    code = tools._cmd_install(
        _args(
            root,
            package_id="web_search",
            source="git:https://example.com/x.git",
            set=["web_search.api_key=abc"],
            yes=True,
            keep_on_health_failure=True,
        )
    )
    assert code == 0
    cmd = calls[0]
    # No --json here -- install/uninstall run with inherited stdio, since
    # a package's own config prompts and the health-check retry/keep/
    # cancel choice need a live terminal.
    assert "--json" not in cmd
    assert cmd[-1] == "install" or "install" in cmd
    assert "web_search" in cmd
    assert "--source" in cmd and "git:https://example.com/x.git" in cmd
    assert "--set" in cmd and "web_search.api_key=abc" in cmd
    assert "--yes" in cmd
    assert "--keep-on-health-failure" in cmd


def test_uninstall_forwards_force_flag(tmp_path, monkeypatch):
    root = make_root(tmp_path)
    _add_fake_backend_venv(root)
    calls = []

    def _fake_run(cmd, cwd, check):
        calls.append(cmd)
        return _FakeCompleted(returncode=0)

    monkeypatch.setattr(tools.subprocess, "run", _fake_run)
    code = tools._cmd_uninstall(_args(root, package_id="web_search", force=True))
    assert code == 0
    assert "--force" in calls[0]
    assert "uninstall" in calls[0]
    assert "web_search" in calls[0]


def test_install_without_backend_venv_fails_cleanly(tmp_path, capsys):
    root = make_root(tmp_path)  # no backend/.venv created
    code = tools._cmd_install(_args(root, package_id="get_time"))
    assert code == 1
    captured = capsys.readouterr()
    assert captured.err or captured.out


def test_list_without_installation_root_fails_cleanly(tmp_path):
    code = tools._cmd_list(_args(tmp_path / "not-a-root"))
    assert code == 1
