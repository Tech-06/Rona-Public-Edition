import json
import os

from installer.steps import tools as tools_step


def _make_backend_venv(root) -> None:
    venv_dir = root / "backend" / ".venv"
    python_path = (
        venv_dir / "Scripts" / "python.exe" if os.name == "nt" else venv_dir / "bin" / "python"
    )
    python_path.parent.mkdir(parents=True)
    python_path.write_text("", encoding="utf-8")


class _FakeCompleted:
    def __init__(self, stdout="", returncode=0):
        self.stdout = stdout
        self.stderr = ""
        self.returncode = returncode


def test_run_skips_when_no_backend_venv(tmp_path, monkeypatch, capsys):
    root = tmp_path / "root"
    (root / "backend").mkdir(parents=True)

    def _fail_if_called(*a, **k):
        raise AssertionError("subprocess.run should not be called without a backend venv")

    monkeypatch.setattr(tools_step.subprocess, "run", _fail_if_called)
    tools_step.run(root)
    assert capsys.readouterr().out == ""


def test_run_skips_when_git_missing(tmp_path, monkeypatch, capsys):
    root = tmp_path / "root"
    _make_backend_venv(root)
    monkeypatch.setattr(tools_step.detect, "git_available", lambda: False)

    def _fail_if_called(*a, **k):
        raise AssertionError("catalog should not be fetched without git")

    monkeypatch.setattr(tools_step.subprocess, "run", _fail_if_called)
    tools_step.run(root)
    assert "bulunamadı" in capsys.readouterr().out


def test_run_skips_gracefully_when_catalog_unreachable(tmp_path, monkeypatch, capsys):
    root = tmp_path / "root"
    _make_backend_venv(root)
    monkeypatch.setattr(tools_step.detect, "git_available", lambda: True)
    monkeypatch.setattr(tools_step.subprocess, "run", lambda *a, **k: _FakeCompleted(stdout=""))
    tools_step.run(root)
    assert "ulaşılamadı" in capsys.readouterr().out


def test_run_nothing_selected_installs_nothing(tmp_path, monkeypatch, capsys):
    root = tmp_path / "root"
    _make_backend_venv(root)
    monkeypatch.setattr(tools_step.detect, "git_available", lambda: True)
    catalog_payload = {
        "ok": True,
        "packages": [{"id": "get_time", "name": "Get Time", "description": "..."}],
    }
    monkeypatch.setattr(
        tools_step.subprocess, "run", lambda *a, **k: _FakeCompleted(stdout=json.dumps(catalog_payload))
    )
    monkeypatch.setattr(tools_step.ui, "select_components", lambda options: [])

    tools_step.run(root)

    assert "seçilmedi" in capsys.readouterr().out


def test_run_installs_selected_packages_and_reports_summary(tmp_path, monkeypatch, capsys):
    root = tmp_path / "root"
    _make_backend_venv(root)
    monkeypatch.setattr(tools_step.detect, "git_available", lambda: True)
    catalog_payload = {
        "ok": True,
        "packages": [
            {"id": "get_time", "name": "Get Time", "description": "..."},
            {"id": "web_search", "name": "Web Search", "description": "..."},
        ],
    }
    install_calls = []

    def _fake_run(cmd, cwd, **kwargs):
        if "available" in cmd:
            return _FakeCompleted(stdout=json.dumps(catalog_payload))
        install_calls.append(cmd)
        # get_time succeeds, web_search fails
        return _FakeCompleted(returncode=0 if "get_time" in cmd else 1)

    monkeypatch.setattr(tools_step.subprocess, "run", _fake_run)
    monkeypatch.setattr(
        tools_step.ui, "select_components", lambda options: ["get_time", "web_search"]
    )

    tools_step.run(root)

    out = capsys.readouterr().out
    assert "get_time" in out
    assert len(install_calls) == 2
    # --json is never passed for the actual install call (inherited stdio,
    # so a package's own config prompts and health-check choice work).
    for cmd in install_calls:
        assert "--json" not in cmd


def test_select_components_options_are_unchecked_by_default(tmp_path, monkeypatch):
    root = tmp_path / "root"
    _make_backend_venv(root)
    monkeypatch.setattr(tools_step.detect, "git_available", lambda: True)
    catalog_payload = {
        "ok": True,
        "packages": [{"id": "get_time", "name": "Get Time", "description": "desc"}],
    }
    monkeypatch.setattr(
        tools_step.subprocess, "run", lambda *a, **k: _FakeCompleted(stdout=json.dumps(catalog_payload))
    )

    captured_options = []

    def _capture(options):
        captured_options.extend(options)
        return []

    monkeypatch.setattr(tools_step.ui, "select_components", _capture)
    tools_step.run(root)

    assert captured_options[0][0] == "get_time"
    assert captured_options[0][2] is False  # not pre-selected


def test_library_packages_are_hidden_and_dependencies_noted(tmp_path, monkeypatch):
    """google_auth provides no tools of its own and comes along automatically,
    so it belongs in the note on google_calendar's line, not on a line of its
    own in a "which tools do you want" list."""
    root = tmp_path / "root"
    _make_backend_venv(root)
    monkeypatch.setattr(tools_step.detect, "git_available", lambda: True)
    catalog_payload = {
        "ok": True,
        "packages": [
            {
                "id": "google_auth",
                "name": "Google Account Authorization",
                "description": "oauth",
                "kind": "library",
                "requires": [],
            },
            {
                "id": "google_calendar",
                "name": "Google Calendar",
                "description": "events",
                "kind": "tool",
                "requires": ["google_auth"],
            },
            {"id": "get_time", "name": "Get Time", "description": "desc", "kind": "tool"},
        ],
    }
    monkeypatch.setattr(
        tools_step.subprocess,
        "run",
        lambda *a, **k: _FakeCompleted(stdout=json.dumps(catalog_payload)),
    )

    captured_options = []

    def _capture(options):
        captured_options.extend(options)
        return []

    monkeypatch.setattr(tools_step.ui, "select_components", _capture)
    tools_step.run(root)

    offered = {opt[0]: opt for opt in captured_options}
    assert "google_auth" not in offered
    assert set(offered) == {"google_calendar", "get_time"}
    assert "google_auth" in offered["google_calendar"][3]
    # A catalog entry without the metadata must not grow a spurious note.
    assert offered["get_time"][3] == ""
