import json

from installer import uninstall


def _make_root(tmp_path):
    root = tmp_path / "rona-checkout"
    for name in ("cli", "backend", "web-client"):
        (root / name).mkdir(parents=True)
    return root


# ---- detection -----------------------------------------------------------------


def test_detect_reports_nothing_on_a_clean_checkout(tmp_path, monkeypatch):
    root = _make_root(tmp_path)
    monkeypatch.setattr(uninstall.state, "state_file", lambda: tmp_path / "no-state.json")
    monkeypatch.setattr(uninstall, "_path_shim_exists", lambda: False)
    available = uninstall._detect(root)
    assert not any(available.values())


def test_detect_finds_backend_venv(tmp_path, monkeypatch):
    root = _make_root(tmp_path)
    (root / "backend" / ".venv").mkdir()
    monkeypatch.setattr(uninstall.state, "state_file", lambda: tmp_path / "no-state.json")
    monkeypatch.setattr(uninstall, "_path_shim_exists", lambda: False)
    assert uninstall._detect(root)["environments"] is True


def test_detect_finds_state_file(tmp_path, monkeypatch):
    root = _make_root(tmp_path)
    state_path = tmp_path / "config.json"
    state_path.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(uninstall.state, "state_file", lambda: state_path)
    monkeypatch.setattr(uninstall, "_path_shim_exists", lambda: False)
    assert uninstall._detect(root)["state"] is True


def test_detect_finds_user_data(tmp_path, monkeypatch):
    root = _make_root(tmp_path)
    (root / "backend" / ".env").write_text("", encoding="utf-8")
    monkeypatch.setattr(uninstall.state, "state_file", lambda: tmp_path / "no-state.json")
    monkeypatch.setattr(uninstall, "_path_shim_exists", lambda: False)
    assert uninstall._detect(root)["user-data"] is True


def test_detect_finds_installed_tool_packages(tmp_path, monkeypatch):
    root = _make_root(tmp_path)
    custom_dir = root / "backend" / "toolbox" / "custom"
    (custom_dir / "get_time").mkdir(parents=True)
    (custom_dir / "__init__.py").write_text("", encoding="utf-8")
    (custom_dir / ".gitkeep").write_text("", encoding="utf-8")
    monkeypatch.setattr(uninstall.state, "state_file", lambda: tmp_path / "no-state.json")
    monkeypatch.setattr(uninstall, "_path_shim_exists", lambda: False)
    assert uninstall._detect(root)["tool-packages"] is True


def test_detect_ignores_bookkeeping_files_in_custom_dir(tmp_path, monkeypatch):
    root = _make_root(tmp_path)
    custom_dir = root / "backend" / "toolbox" / "custom"
    custom_dir.mkdir(parents=True)
    (custom_dir / "__init__.py").write_text("", encoding="utf-8")
    (custom_dir / ".gitkeep").write_text("", encoding="utf-8")
    monkeypatch.setattr(uninstall.state, "state_file", lambda: tmp_path / "no-state.json")
    monkeypatch.setattr(uninstall, "_path_shim_exists", lambda: False)
    assert uninstall._detect(root)["tool-packages"] is False


def test_detect_finds_runtime_pid_files(tmp_path, monkeypatch):
    root = _make_root(tmp_path)
    (root / "backend" / "rona.pid").write_text("123", encoding="utf-8")
    monkeypatch.setattr(uninstall.state, "state_file", lambda: tmp_path / "no-state.json")
    monkeypatch.setattr(uninstall, "_path_shim_exists", lambda: False)
    assert uninstall._detect(root)["runtime"] is True


# ---- removers --------------------------------------------------------------------


def test_remove_environments_deletes_venvs_and_build_output(tmp_path):
    root = _make_root(tmp_path)
    (root / "cli" / ".venv").mkdir()
    (root / "backend" / ".venv").mkdir()
    (root / "web-client" / ".venv").mkdir()
    (root / "web-client" / "webui" / "dist").mkdir(parents=True)

    uninstall._remove_environments(root)

    assert not (root / "cli" / ".venv").exists()
    assert not (root / "backend" / ".venv").exists()
    assert not (root / "web-client" / ".venv").exists()
    assert not (root / "web-client" / "webui" / "dist").exists()


def test_remove_user_data_deletes_env_and_db_but_not_examples(tmp_path):
    root = _make_root(tmp_path)
    (root / "backend" / ".env").write_text("AUTH_TOKEN=x", encoding="utf-8")
    (root / "backend" / ".env.example").write_text("AUTH_TOKEN=", encoding="utf-8")
    (root / "backend" / "rona.db").write_text("", encoding="utf-8")
    (root / "backend" / "rona.log.1").write_text("", encoding="utf-8")

    uninstall._remove_user_data(root)

    assert not (root / "backend" / ".env").exists()
    assert not (root / "backend" / "rona.db").exists()
    assert not (root / "backend" / "rona.log.1").exists()
    assert (root / "backend" / ".env.example").exists()  # template, never touched


def test_remove_tool_packages_deletes_packages_but_not_bookkeeping(tmp_path):
    root = _make_root(tmp_path)
    custom_dir = root / "backend" / "toolbox" / "custom"
    (custom_dir / "get_time").mkdir(parents=True)
    (custom_dir / "get_time" / "manifest.json").write_text("{}", encoding="utf-8")
    (custom_dir / "__init__.py").write_text("", encoding="utf-8")
    (custom_dir / ".gitkeep").write_text("", encoding="utf-8")
    (custom_dir / "installed.json").write_text('{"packages": {}}', encoding="utf-8")

    uninstall._remove_tool_packages(root)

    assert not (custom_dir / "get_time").exists()
    assert not (custom_dir / "installed.json").exists()
    assert (custom_dir / "__init__.py").exists()
    assert (custom_dir / ".gitkeep").exists()


def test_remove_runtime_deletes_pid_lock_and_log_files(tmp_path):
    root = _make_root(tmp_path)
    (root / "backend" / "rona.pid").write_text("1", encoding="utf-8")
    (root / "web-client" / "webui.pid").write_text("2", encoding="utf-8")
    (root / "web-client" / "webui.lock").write_text("", encoding="utf-8")
    (root / "web-client" / "webui.log").write_text("", encoding="utf-8")
    (root / "web-client" / "webui.log.1").write_text("", encoding="utf-8")

    uninstall._remove_runtime(root)

    assert not (root / "backend" / "rona.pid").exists()
    assert not (root / "web-client" / "webui.pid").exists()
    assert not (root / "web-client" / "webui.lock").exists()
    assert not (root / "web-client" / "webui.log").exists()
    assert not (root / "web-client" / "webui.log.1").exists()


def test_remove_state_deletes_config_file(tmp_path, monkeypatch):
    state_path = tmp_path / "config.json"
    state_path.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(uninstall.state, "state_file", lambda: state_path)
    uninstall._remove_state(tmp_path)
    assert not state_path.exists()


# ---- process stopping -------------------------------------------------------------


def test_stop_running_processes_noop_when_nothing_tracked(tmp_path, capsys):
    root = _make_root(tmp_path)
    uninstall._stop_running_processes(root, auto_yes=False, interactive=True)
    assert capsys.readouterr().out == ""


def test_stop_running_processes_never_blocks_in_non_interactive_without_yes(tmp_path, monkeypatch, capsys):
    root = _make_root(tmp_path)
    (root / "backend" / "rona.pid").write_text("999999", encoding="utf-8")
    monkeypatch.setattr(uninstall.procutil, "pid_alive", lambda pid: True)

    def _fail_if_called(*a, **k):
        raise AssertionError("confirm() must never be called in non-interactive mode")

    monkeypatch.setattr(uninstall.ui, "confirm", _fail_if_called)
    kill_calls = []
    monkeypatch.setattr(uninstall.procutil, "kill_tree", lambda pid: kill_calls.append(pid))

    uninstall._stop_running_processes(root, auto_yes=False, interactive=False)

    assert kill_calls == []
    assert "çalışıyor" in capsys.readouterr().out


def test_stop_running_processes_auto_yes_kills_without_asking(tmp_path, monkeypatch):
    root = _make_root(tmp_path)
    (root / "backend" / "rona.pid").write_text("999999", encoding="utf-8")
    monkeypatch.setattr(uninstall.procutil, "pid_alive", lambda pid: True)

    def _fail_if_called(*a, **k):
        raise AssertionError("confirm() should not be called when auto_yes=True")

    monkeypatch.setattr(uninstall.ui, "confirm", _fail_if_called)
    kill_calls = []
    monkeypatch.setattr(uninstall.procutil, "kill_tree", lambda pid: kill_calls.append(pid))

    uninstall._stop_running_processes(root, auto_yes=True, interactive=False)

    assert kill_calls == [999999]


# ---- main() ------------------------------------------------------------------------


def test_main_nothing_found_is_a_clean_noop(tmp_path, monkeypatch, capsys):
    root = _make_root(tmp_path)
    monkeypatch.setattr(uninstall, "REPO_ROOT", root)
    monkeypatch.setattr(uninstall.state, "state_file", lambda: tmp_path / "no-state.json")
    monkeypatch.setattr(uninstall, "_path_shim_exists", lambda: False)

    exit_code = uninstall.main(["--yes", "--items", "environments"])

    assert exit_code == 0
    assert "bulunamadı" in capsys.readouterr().out


def test_main_non_interactive_requires_items(tmp_path, monkeypatch, capsys):
    root = _make_root(tmp_path)
    (root / "backend" / ".venv").mkdir(parents=True)
    monkeypatch.setattr(uninstall, "REPO_ROOT", root)
    monkeypatch.setattr(uninstall.state, "state_file", lambda: tmp_path / "no-state.json")
    monkeypatch.setattr(uninstall, "_path_shim_exists", lambda: False)

    exit_code = uninstall.main(["--yes"])

    assert exit_code == 1
    assert "items" in capsys.readouterr().err


def test_main_removes_only_the_requested_items(tmp_path, monkeypatch):
    root = _make_root(tmp_path)
    (root / "backend" / ".venv").mkdir(parents=True)
    (root / "backend" / ".env").write_text("AUTH_TOKEN=x", encoding="utf-8")
    monkeypatch.setattr(uninstall, "REPO_ROOT", root)
    monkeypatch.setattr(uninstall.state, "state_file", lambda: tmp_path / "no-state.json")
    monkeypatch.setattr(uninstall, "_path_shim_exists", lambda: False)

    exit_code = uninstall.main(["--yes", "--items", "environments"])

    assert exit_code == 0
    assert not (root / "backend" / ".venv").exists()
    assert (root / "backend" / ".env").exists()  # user-data was not requested


def test_main_json_mode_reports_removed_items(tmp_path, monkeypatch, capsys):
    root = _make_root(tmp_path)
    (root / "backend" / ".venv").mkdir(parents=True)
    monkeypatch.setattr(uninstall, "REPO_ROOT", root)
    monkeypatch.setattr(uninstall.state, "state_file", lambda: tmp_path / "no-state.json")
    monkeypatch.setattr(uninstall, "_path_shim_exists", lambda: False)

    exit_code = uninstall.main(["--json", "--items", "environments"])

    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload == {"ok": True, "removed": ["environments"]}


def test_main_rejects_unknown_items(tmp_path, monkeypatch, capsys):
    root = _make_root(tmp_path)
    (root / "backend" / ".venv").mkdir(parents=True)
    monkeypatch.setattr(uninstall, "REPO_ROOT", root)
    monkeypatch.setattr(uninstall.state, "state_file", lambda: tmp_path / "no-state.json")
    monkeypatch.setattr(uninstall, "_path_shim_exists", lambda: False)

    exit_code = uninstall.main(["--yes", "--items", "bogus"])

    assert exit_code == 1
    assert "bogus" in capsys.readouterr().err


def test_main_interactive_selection_none_picked_removes_nothing(tmp_path, monkeypatch, capsys):
    root = _make_root(tmp_path)
    (root / "backend" / ".venv").mkdir(parents=True)
    monkeypatch.setattr(uninstall, "REPO_ROOT", root)
    monkeypatch.setattr(uninstall.state, "state_file", lambda: tmp_path / "no-state.json")
    monkeypatch.setattr(uninstall, "_path_shim_exists", lambda: False)
    monkeypatch.setattr(uninstall, "_select_items", lambda available: [])

    exit_code = uninstall.main(["--lang", "en"])

    assert exit_code == 0
    assert (root / "backend" / ".venv").exists()
    assert "Nothing selected" in capsys.readouterr().out


def test_main_interactive_user_data_asks_second_confirmation_and_declines(tmp_path, monkeypatch):
    root = _make_root(tmp_path)
    (root / "backend" / ".env").write_text("AUTH_TOKEN=x", encoding="utf-8")
    monkeypatch.setattr(uninstall, "REPO_ROOT", root)
    monkeypatch.setattr(uninstall.state, "state_file", lambda: tmp_path / "no-state.json")
    monkeypatch.setattr(uninstall, "_path_shim_exists", lambda: False)
    monkeypatch.setattr(uninstall, "_select_items", lambda available: ["user-data"])
    monkeypatch.setattr(uninstall.ui, "confirm", lambda *a, **k: False)

    uninstall.main(["--lang", "en"])

    assert (root / "backend" / ".env").exists()  # declined -- must survive


def test_main_interactive_user_data_confirmed_removes_it(tmp_path, monkeypatch):
    root = _make_root(tmp_path)
    (root / "backend" / ".env").write_text("AUTH_TOKEN=x", encoding="utf-8")
    monkeypatch.setattr(uninstall, "REPO_ROOT", root)
    monkeypatch.setattr(uninstall.state, "state_file", lambda: tmp_path / "no-state.json")
    monkeypatch.setattr(uninstall, "_path_shim_exists", lambda: False)
    monkeypatch.setattr(uninstall, "_select_items", lambda available: ["user-data"])
    monkeypatch.setattr(uninstall.ui, "confirm", lambda *a, **k: True)

    uninstall.main(["--lang", "en"])

    assert not (root / "backend" / ".env").exists()


def test_main_never_touches_the_repo_root_itself(tmp_path, monkeypatch):
    root = _make_root(tmp_path)
    (root / "backend" / ".venv").mkdir(parents=True)
    monkeypatch.setattr(uninstall, "REPO_ROOT", root)
    monkeypatch.setattr(uninstall.state, "state_file", lambda: tmp_path / "no-state.json")
    monkeypatch.setattr(uninstall, "_path_shim_exists", lambda: False)
    # "path" is deliberately excluded from the items exercised here --
    # pathsetup.remove() touches the real registry/rc file, and that is
    # covered on its own, fully mocked, in test_pathsetup.py. This test
    # is only about the repo root surviving every *filesystem* remover.
    fs_items = [item for item in uninstall._ITEMS if item != "path"]

    uninstall.main(["--yes", "--items", ",".join(fs_items)])

    assert root.is_dir()  # the checkout itself always survives
