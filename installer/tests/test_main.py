import io
from types import SimpleNamespace

from installer import main as main_module
from installer.steps import backend as backend_step
from installer.steps import cli as cli_step
from installer.steps import web as web_step
from rona_cli import envio


def test_ensure_utf8_streams_reconfigures_text_streams(monkeypatch, tmp_path):
    raw = (tmp_path / "out.txt").open("wb")
    wrapper = io.TextIOWrapper(raw, encoding="cp1252")
    monkeypatch.setattr("sys.stdout", wrapper)
    monkeypatch.setattr("sys.stderr", wrapper)
    main_module._ensure_utf8_streams()
    assert wrapper.encoding.lower().replace("-", "") == "utf8"
    wrapper.close()


def _make_root(tmp_path):
    root = tmp_path / "rona-checkout"
    for name in ("cli", "backend", "web-client"):
        (root / name).mkdir(parents=True)
    (root / "backend" / ".env.example").write_text("AUTH_TOKEN=\n", encoding="utf-8")
    (root / "web-client" / ".env.example").write_text("AUTH_TOKEN=\n", encoding="utf-8")
    return root


def test_select_components_repair_mode():
    args = SimpleNamespace(repair=True, components=None, yes=False, json=False)
    installed = SimpleNamespace(as_dict=lambda: {"cli": True, "backend": False, "web": True})
    assert main_module._select_components(args, installed) == ["cli", "web"]


def test_select_components_repair_mode_none_installed_errors(capsys):
    args = SimpleNamespace(repair=True, components=None, yes=False, json=False)
    installed = SimpleNamespace(as_dict=lambda: {"cli": False, "backend": False, "web": False})
    assert main_module._select_components(args, installed) is None
    assert "bulunamadı" in capsys.readouterr().err


def test_select_components_explicit_list():
    args = SimpleNamespace(repair=False, components="backend,cli", yes=False, json=False)
    installed = SimpleNamespace(as_dict=lambda: {"cli": False, "backend": False, "web": False})
    assert main_module._select_components(args, installed) == ["cli", "backend"]


def test_select_components_explicit_unknown_errors(capsys):
    args = SimpleNamespace(repair=False, components="bogus", yes=False, json=False)
    installed = SimpleNamespace(as_dict=lambda: {"cli": False, "backend": False, "web": False})
    assert main_module._select_components(args, installed) is None
    assert "Bilinmeyen" in capsys.readouterr().err


def test_select_components_yes_flag_selects_all():
    args = SimpleNamespace(repair=False, components=None, yes=True, json=False)
    installed = SimpleNamespace(as_dict=lambda: {"cli": False, "backend": False, "web": False})
    assert main_module._select_components(args, installed) == ["cli", "backend", "web"]


def test_select_components_json_flag_selects_all_without_prompting():
    args = SimpleNamespace(repair=False, components=None, yes=False, json=True)
    installed = SimpleNamespace(as_dict=lambda: {"cli": False, "backend": False, "web": False})
    assert main_module._select_components(args, installed) == ["cli", "backend", "web"]


def test_select_components_uses_interactive_menu(monkeypatch):
    args = SimpleNamespace(repair=False, components=None, yes=False, json=False)
    installed = SimpleNamespace(as_dict=lambda: {"cli": True, "backend": False, "web": False})
    monkeypatch.setattr(main_module.ui, "select_components", lambda options: ["backend"])
    assert main_module._select_components(args, installed) == ["backend"]


def test_main_end_to_end_happy_path(tmp_path, monkeypatch, capsys):
    root = _make_root(tmp_path)
    monkeypatch.setattr(main_module, "REPO_ROOT", root)
    monkeypatch.setattr(main_module.state, "state_file", lambda: tmp_path / "home" / ".rona" / "config.json")
    monkeypatch.setattr(main_module.detect, "python_version", lambda: (3, 12, 0))
    monkeypatch.setattr(main_module.detect, "git_available", lambda: True)
    monkeypatch.setattr(main_module.detect, "node_version", lambda: (20, 0, 0))
    monkeypatch.setattr(cli_step, "install", lambda root_, *, reinstall: True)
    monkeypatch.setattr(backend_step, "install", lambda root_, *, reinstall: True)
    monkeypatch.setattr(web_step, "install", lambda root_, *, reinstall: True)

    # backend_step/web_step are stubbed out, so nothing actually
    # materializes their .env -- do what the real steps would have done,
    # since ensure_auth_token needs both files to exist.
    (root / "backend" / ".env").write_text("", encoding="utf-8")
    (root / "web-client" / ".env").write_text("", encoding="utf-8")

    exit_code = main_module.main(["--yes", "--json"])

    assert exit_code == 0
    backend_token = envio.read_env_file(root / "backend" / ".env")["AUTH_TOKEN"]
    web_token = envio.read_env_file(root / "web-client" / ".env")["AUTH_TOKEN"]
    assert backend_token == web_token
    assert len(backend_token) > 20

    import json

    json_lines = [line for line in capsys.readouterr().out.splitlines() if line.startswith("{")]
    assert json_lines
    payload = json.loads(json_lines[-1])
    assert payload["ok"] is True
    assert payload["results"] == {"cli": True, "backend": True, "web": True}

    state_data = main_module.state.read_state()
    assert state_data["root"] == str(root)


def test_main_reports_failure_when_a_step_fails(tmp_path, monkeypatch):
    root = _make_root(tmp_path)
    monkeypatch.setattr(main_module, "REPO_ROOT", root)
    monkeypatch.setattr(main_module.state, "state_file", lambda: tmp_path / "home" / ".rona" / "config.json")
    monkeypatch.setattr(main_module.detect, "python_version", lambda: (3, 12, 0))
    monkeypatch.setattr(main_module.detect, "git_available", lambda: True)
    monkeypatch.setattr(cli_step, "install", lambda root_, *, reinstall: True)
    monkeypatch.setattr(backend_step, "install", lambda root_, *, reinstall: False)

    exit_code = main_module.main(["--components", "cli,backend"])

    assert exit_code == 1
    assert main_module.state.read_state() is None


def test_main_rejects_python_below_minimum(tmp_path, monkeypatch, capsys):
    root = _make_root(tmp_path)
    monkeypatch.setattr(main_module, "REPO_ROOT", root)
    monkeypatch.setattr(main_module.detect, "python_version", lambda: (3, 9, 0))

    exit_code = main_module.main(["--components", "cli"])

    assert exit_code == 1
    assert "3.11" in capsys.readouterr().err
