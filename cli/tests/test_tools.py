import json
import os
from types import SimpleNamespace

from rona_cli import i18n
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
        "purge": False,
        "edit": False,
        "action_id": "some_action",
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


def test_available_shows_dependencies_and_installed_marker(tmp_path, monkeypatch, capsys):
    root = make_root(tmp_path)
    _add_fake_backend_venv(root)

    def _fake_run(cmd, cwd, capture_output, text, check):
        payload = {
            "ok": True,
            "packages": [
                {
                    "id": "google_calendar",
                    "version": "1.1.0",
                    "name": "Google Calendar",
                    "description": "events",
                    "kind": "tool",
                    "requires": ["google_auth"],
                    "installed": False,
                },
                {
                    "id": "google_auth",
                    "version": "2.0.0",
                    "name": "Google Account Authorization",
                    "description": "oauth",
                    "kind": "library",
                    "requires": [],
                    "installed": True,
                },
            ],
        }
        return _FakeCompleted(stdout=json.dumps(payload) + "\n")

    monkeypatch.setattr(tools.subprocess, "run", _fake_run)
    assert tools._cmd_available(_args(root)) == 0
    out = capsys.readouterr().out
    assert "google_auth" in out
    # The dependency has to be visible before the user commits to an install.
    assert "google_calendar" in out and "google_auth" in out.split("google_calendar")[1]


def test_available_tolerates_a_catalog_without_dependency_metadata(
    tmp_path, monkeypatch, capsys
):
    """An older index publishes neither key; saying nothing beats implying
    the package has no dependencies."""
    root = make_root(tmp_path)
    _add_fake_backend_venv(root)

    def _fake_run(cmd, cwd, capture_output, text, check):
        payload = {
            "ok": True,
            "packages": [
                {"id": "old", "version": "1.0.0", "name": "Old", "description": "x"}
            ],
        }
        return _FakeCompleted(stdout=json.dumps(payload) + "\n")

    monkeypatch.setattr(tools.subprocess, "run", _fake_run)
    assert tools._cmd_available(_args(root)) == 0
    assert "old" in capsys.readouterr().out


def test_config_show_masks_secrets_and_is_captured(tmp_path, monkeypatch, capsys):
    root = make_root(tmp_path)
    _add_fake_backend_venv(root)
    calls = []

    def _fake_run(cmd, cwd, capture_output, text, check):
        calls.append(cmd)
        payload = {
            "ok": True,
            "package": "google_calendar",
            "fields": [
                {
                    "key": "accounts",
                    "label": "Allowed accounts",
                    "description": "",
                    "type": "list",
                    "secret": False,
                    "set": True,
                    "value": ["work", "home"],
                },
                {
                    "key": "api_key",
                    "label": "Key",
                    "description": "",
                    "type": "string",
                    "secret": True,
                    "set": True,
                    "value": None,
                },
            ],
        }
        return _FakeCompleted(stdout=json.dumps(payload) + "\n")

    monkeypatch.setattr(tools.subprocess, "run", _fake_run)
    assert tools._cmd_config(_args(root, package_id="google_calendar")) == 0
    out = capsys.readouterr().out
    assert "work, home" in out
    assert "api_key" in out
    assert calls[0].index("--json") < calls[0].index("config")


def test_config_set_is_captured_and_reports_health(tmp_path, monkeypatch, capsys):
    root = make_root(tmp_path)
    _add_fake_backend_venv(root)
    calls = []

    def _fake_run(cmd, cwd, capture_output, text, check):
        calls.append(cmd)
        payload = {
            "ok": True,
            "package": "google_calendar",
            "changed": ["accounts"],
            "health_ok": False,
            "detail": "no authorization for account(s): work",
        }
        return _FakeCompleted(stdout=json.dumps(payload) + "\n")

    monkeypatch.setattr(tools.subprocess, "run", _fake_run)
    code = tools._cmd_config(
        _args(root, package_id="google_calendar", set=["accounts=work"])
    )
    assert code == 0
    captured = capsys.readouterr()
    assert "accounts" in captured.out
    assert "no authorization" in captured.out + captured.err
    assert "--set" in calls[0] and "accounts=work" in calls[0]


def test_config_edit_inherits_stdio(tmp_path, monkeypatch):
    """--edit walks every field, masking secrets with getpass, so it cannot be
    captured and re-printed."""
    root = make_root(tmp_path)
    _add_fake_backend_venv(root)
    calls = []

    def _fake_run(cmd, cwd, check):
        calls.append(cmd)
        return _FakeCompleted(returncode=0)

    monkeypatch.setattr(tools.subprocess, "run", _fake_run)
    assert tools._cmd_config(_args(root, package_id="google_auth", edit=True)) == 0
    assert "--edit" in calls[0]


def test_actions_lists_and_flags_terminal_only(tmp_path, monkeypatch, capsys):
    root = make_root(tmp_path)
    _add_fake_backend_venv(root)

    def _fake_run(cmd, cwd, capture_output, text, check):
        payload = {
            "ok": True,
            "package": "google_auth",
            "actions": [
                {
                    "id": "add_account",
                    "label": "Add a Google account",
                    "description": "works anywhere",
                    "destructive": False,
                    "cli_only": False,
                    "params": [{"key": "account_name"}],
                },
                {
                    "id": "add_account_here",
                    "label": "Use this machine's browser",
                    "description": "",
                    "destructive": False,
                    "cli_only": True,
                    "params": [],
                },
            ],
        }
        return _FakeCompleted(stdout=json.dumps(payload) + "\n")

    monkeypatch.setattr(tools.subprocess, "run", _fake_run)
    assert tools._cmd_actions(_args(root, package_id="google_auth")) == 0
    out = capsys.readouterr().out
    assert "add_account" in out
    assert "account_name" in out
    assert i18n.t("tools.action_cli_only") in out


def test_run_inherits_stdio_and_forwards_json(tmp_path, monkeypatch):
    """An action that answers input_required has to ask on this terminal, and
    the authorization link it prints must reach the user unmangled."""
    root = make_root(tmp_path)
    _add_fake_backend_venv(root)
    calls = []

    def _fake_run(cmd, cwd, check):
        calls.append(cmd)
        return _FakeCompleted(returncode=0)

    monkeypatch.setattr(tools.subprocess, "run", _fake_run)
    code = tools._cmd_run(
        _args(
            root,
            package_id="google_auth",
            action_id="add_account",
            set=["account_name=work"],
        )
    )
    assert code == 0
    cmd = calls[0]
    assert "--json" not in cmd
    assert cmd[-4:] == ["run", "google_auth", "add_account"] or "run" in cmd
    assert "--set" in cmd and "account_name=work" in cmd

    calls.clear()
    tools._cmd_run(
        _args(root, package_id="google_auth", action_id="list_accounts", json=True)
    )
    # With `rona --json` the manager emits the JSON itself, since we are not
    # capturing its output.
    assert calls[0].index("--json") < calls[0].index("run")


def test_uninstall_forwards_purge_flag(tmp_path, monkeypatch):
    root = make_root(tmp_path)
    _add_fake_backend_venv(root)
    calls = []

    def _fake_run(cmd, cwd, check):
        calls.append(cmd)
        return _FakeCompleted(returncode=0)

    monkeypatch.setattr(tools.subprocess, "run", _fake_run)
    assert tools._cmd_uninstall(_args(root, package_id="google_auth", purge=True)) == 0
    assert "--purge" in calls[0]
