import os

from installer import pathsetup

# Every test here monkeypatches the actual registry/PATH/rc-file touching
# functions -- none of these tests may mutate the real machine's PATH,
# Windows registry, or shell rc files.


def _make_windows_venv(tmp_path):
    scripts_dir = tmp_path / "cli-venv" / "Scripts"
    scripts_dir.mkdir(parents=True)
    (scripts_dir / "rona.exe").write_text("", encoding="utf-8")
    return tmp_path / "cli-venv"


def _make_posix_venv(tmp_path):
    bin_dir = tmp_path / "cli-venv" / "bin"
    bin_dir.mkdir(parents=True)
    (bin_dir / "rona").write_text("#!/usr/bin/env python\n", encoding="utf-8")
    return tmp_path / "cli-venv"


# ---- Windows ------------------------------------------------------------


def test_write_windows_shim_creates_cmd_file(tmp_path, monkeypatch):
    venv_dir = _make_windows_venv(tmp_path)
    fake_bin_dir = tmp_path / "bin"
    monkeypatch.setattr(pathsetup, "_windows_bin_dir", lambda: fake_bin_dir)

    result = pathsetup._write_windows_shim(venv_dir / "Scripts")

    assert result == fake_bin_dir
    shim = fake_bin_dir / "rona.cmd"
    assert shim.is_file()
    assert "rona.exe" in shim.read_text(encoding="utf-8")


def test_is_on_user_path_windows_true_when_present(monkeypatch, tmp_path):
    bin_dir = tmp_path / "Rona" / "bin"
    monkeypatch.setattr(pathsetup, "_read_user_path_windows", lambda: f"C:\\Other;{bin_dir}\\;C:\\Another")
    assert pathsetup._is_on_user_path_windows(bin_dir) is True


def test_is_on_user_path_windows_false_when_absent(monkeypatch, tmp_path):
    bin_dir = tmp_path / "Rona" / "bin"
    monkeypatch.setattr(pathsetup, "_read_user_path_windows", lambda: "C:\\Other;C:\\Another")
    assert pathsetup._is_on_user_path_windows(bin_dir) is False


def test_add_to_user_path_windows_appends_and_broadcasts(monkeypatch, tmp_path):
    bin_dir = tmp_path / "Rona" / "bin"
    monkeypatch.setattr(pathsetup, "_read_user_path_windows", lambda: "C:\\Existing")
    written = {}
    monkeypatch.setattr(pathsetup, "_write_user_path_windows", lambda value: written.setdefault("value", value))
    broadcasted = []
    monkeypatch.setattr(pathsetup, "_broadcast_environment_change", lambda: broadcasted.append(True))

    pathsetup._add_to_user_path_windows(bin_dir)

    assert written["value"] == f"C:\\Existing;{bin_dir}"
    assert broadcasted == [True]


def test_setup_windows_full_flow_adds_when_missing(tmp_path, monkeypatch, capsys):
    venv_dir = _make_windows_venv(tmp_path)
    fake_bin_dir = tmp_path / "bin"
    monkeypatch.setattr(pathsetup, "_windows_bin_dir", lambda: fake_bin_dir)
    monkeypatch.setattr(pathsetup, "_read_user_path_windows", lambda: "C:\\Existing")
    written = {}
    monkeypatch.setattr(pathsetup, "_write_user_path_windows", lambda value: written.setdefault("value", value))
    monkeypatch.setattr(pathsetup, "_broadcast_environment_change", lambda: None)

    pathsetup._setup_windows(venv_dir)

    assert (fake_bin_dir / "rona.cmd").is_file()
    assert str(fake_bin_dir) in written["value"]
    assert "eklendi" in capsys.readouterr().out


def test_setup_windows_skips_when_already_on_path(tmp_path, monkeypatch, capsys):
    venv_dir = _make_windows_venv(tmp_path)
    fake_bin_dir = tmp_path / "bin"
    monkeypatch.setattr(pathsetup, "_windows_bin_dir", lambda: fake_bin_dir)
    monkeypatch.setattr(pathsetup, "_read_user_path_windows", lambda: f"{fake_bin_dir}")
    write_calls = []
    monkeypatch.setattr(pathsetup, "_write_user_path_windows", lambda value: write_calls.append(value))

    pathsetup._setup_windows(venv_dir)

    assert write_calls == []
    assert "zaten" in capsys.readouterr().out


def test_setup_windows_missing_exe_skips_gracefully(tmp_path, capsys):
    empty_venv = tmp_path / "empty-venv"
    (empty_venv / "Scripts").mkdir(parents=True)
    pathsetup._setup_windows(empty_venv)
    assert "bulunamadı" in capsys.readouterr().out


# ---- macOS / Linux --------------------------------------------------------


def test_write_posix_shim_creates_executable_script(tmp_path, monkeypatch):
    venv_dir = _make_posix_venv(tmp_path)
    fake_bin_dir = tmp_path / "home" / ".local" / "bin"
    monkeypatch.setattr(pathsetup, "_posix_bin_dir", lambda: fake_bin_dir)

    result = pathsetup._write_posix_shim(venv_dir)

    assert result == fake_bin_dir
    shim = fake_bin_dir / "rona"
    assert shim.is_file()
    assert "rona" in shim.read_text(encoding="utf-8")


def test_write_posix_shim_missing_target_returns_none(tmp_path, monkeypatch):
    empty_venv = tmp_path / "empty-venv"
    (empty_venv / "bin").mkdir(parents=True)
    monkeypatch.setattr(pathsetup, "_posix_bin_dir", lambda: tmp_path / "home" / ".local" / "bin")
    assert pathsetup._write_posix_shim(empty_venv) is None


def test_is_on_path_true_when_present(monkeypatch, tmp_path):
    bin_dir = tmp_path / ".local" / "bin"
    monkeypatch.setenv("PATH", f"/usr/bin{os.pathsep}{bin_dir}")
    assert pathsetup._is_on_path(bin_dir) is True


def test_is_on_path_false_when_absent(monkeypatch, tmp_path):
    bin_dir = tmp_path / ".local" / "bin"
    monkeypatch.setenv("PATH", "/usr/bin")
    assert pathsetup._is_on_path(bin_dir) is False


def test_rc_file_for_shell_prefers_zshrc(monkeypatch, tmp_path):
    monkeypatch.setenv("SHELL", "/bin/zsh")
    monkeypatch.setattr(pathsetup.Path, "home", classmethod(lambda cls: tmp_path))
    assert pathsetup._rc_file_for_shell() == tmp_path / ".zshrc"


def test_rc_file_for_shell_bash_prefers_existing_bashrc(monkeypatch, tmp_path):
    monkeypatch.setenv("SHELL", "/bin/bash")
    (tmp_path / ".bashrc").write_text("", encoding="utf-8")
    monkeypatch.setattr(pathsetup.Path, "home", classmethod(lambda cls: tmp_path))
    assert pathsetup._rc_file_for_shell() == tmp_path / ".bashrc"


def test_rc_file_for_shell_bash_falls_back_to_profile(monkeypatch, tmp_path):
    monkeypatch.setenv("SHELL", "/bin/bash")
    monkeypatch.setattr(pathsetup.Path, "home", classmethod(lambda cls: tmp_path))
    assert pathsetup._rc_file_for_shell() == tmp_path / ".profile"


def test_setup_posix_already_on_path_skips_rc_edit(tmp_path, monkeypatch, capsys):
    venv_dir = _make_posix_venv(tmp_path)
    fake_bin_dir = tmp_path / "home" / ".local" / "bin"
    monkeypatch.setattr(pathsetup, "_posix_bin_dir", lambda: fake_bin_dir)
    monkeypatch.setattr(pathsetup, "_is_on_path", lambda bin_dir: True)

    pathsetup._setup_posix(venv_dir, auto_yes=False)

    assert "zaten" in capsys.readouterr().out


def test_setup_posix_confirms_before_editing_rc(tmp_path, monkeypatch, capsys):
    venv_dir = _make_posix_venv(tmp_path)
    fake_bin_dir = tmp_path / "home" / ".local" / "bin"
    rc_file = tmp_path / "home" / ".profile"
    monkeypatch.setattr(pathsetup, "_posix_bin_dir", lambda: fake_bin_dir)
    monkeypatch.setattr(pathsetup, "_is_on_path", lambda bin_dir: False)
    monkeypatch.setattr(pathsetup, "_rc_file_for_shell", lambda: rc_file)
    monkeypatch.setattr(pathsetup.ui, "confirm", lambda *a, **k: True)

    pathsetup._setup_posix(venv_dir, auto_yes=False)

    assert rc_file.is_file()
    assert ".local/bin" in rc_file.read_text(encoding="utf-8")
    assert "güncellendi" in capsys.readouterr().out


def test_setup_posix_declines_rc_edit(tmp_path, monkeypatch):
    venv_dir = _make_posix_venv(tmp_path)
    fake_bin_dir = tmp_path / "home" / ".local" / "bin"
    rc_file = tmp_path / "home" / ".profile"
    monkeypatch.setattr(pathsetup, "_posix_bin_dir", lambda: fake_bin_dir)
    monkeypatch.setattr(pathsetup, "_is_on_path", lambda bin_dir: False)
    monkeypatch.setattr(pathsetup, "_rc_file_for_shell", lambda: rc_file)
    monkeypatch.setattr(pathsetup.ui, "confirm", lambda *a, **k: False)

    pathsetup._setup_posix(venv_dir, auto_yes=False)

    assert not rc_file.exists()


def test_setup_posix_auto_yes_skips_confirmation(tmp_path, monkeypatch):
    venv_dir = _make_posix_venv(tmp_path)
    fake_bin_dir = tmp_path / "home" / ".local" / "bin"
    rc_file = tmp_path / "home" / ".profile"
    monkeypatch.setattr(pathsetup, "_posix_bin_dir", lambda: fake_bin_dir)
    monkeypatch.setattr(pathsetup, "_is_on_path", lambda bin_dir: False)
    monkeypatch.setattr(pathsetup, "_rc_file_for_shell", lambda: rc_file)

    def _fail_if_called(*a, **k):
        raise AssertionError("confirm() should not be called when auto_yes=True")

    monkeypatch.setattr(pathsetup.ui, "confirm", _fail_if_called)

    pathsetup._setup_posix(venv_dir, auto_yes=True)

    assert rc_file.is_file()


def test_setup_posix_missing_rona_script_skips_gracefully(tmp_path, monkeypatch, capsys):
    empty_venv = tmp_path / "empty-venv"
    (empty_venv / "bin").mkdir(parents=True)
    monkeypatch.setattr(pathsetup, "_posix_bin_dir", lambda: tmp_path / "home" / ".local" / "bin")

    pathsetup._setup_posix(empty_venv, auto_yes=True)

    assert "bulunamadı" in capsys.readouterr().out


# ---- setup() platform dispatch --------------------------------------------


def test_setup_dispatches_to_windows(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(pathsetup.sys, "platform", "win32")
    monkeypatch.setattr(pathsetup, "_setup_windows", lambda venv_dir: calls.append(("win", venv_dir)))
    pathsetup.setup(tmp_path, auto_yes=True)
    assert calls == [("win", tmp_path)]


def test_setup_dispatches_to_posix(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(pathsetup.sys, "platform", "linux")
    monkeypatch.setattr(pathsetup, "_setup_posix", lambda venv_dir, *, auto_yes: calls.append((venv_dir, auto_yes)))
    pathsetup.setup(tmp_path, auto_yes=False)
    assert calls == [(tmp_path, False)]


# ---- remove() ---------------------------------------------------------------


def test_remove_dispatches_to_windows(monkeypatch):
    calls = []
    monkeypatch.setattr(pathsetup.sys, "platform", "win32")
    monkeypatch.setattr(pathsetup, "_remove_windows", lambda: calls.append("win"))
    pathsetup.remove(auto_yes=True)
    assert calls == ["win"]


def test_remove_dispatches_to_posix(monkeypatch):
    calls = []
    monkeypatch.setattr(pathsetup.sys, "platform", "linux")
    monkeypatch.setattr(pathsetup, "_remove_posix", lambda *, auto_yes: calls.append(auto_yes))
    pathsetup.remove(auto_yes=False)
    assert calls == [False]


def test_remove_windows_deletes_shim_and_path_entry(tmp_path, monkeypatch, capsys):
    fake_bin_dir = tmp_path / "bin"
    fake_bin_dir.mkdir()
    (fake_bin_dir / "rona.cmd").write_text("", encoding="utf-8")
    monkeypatch.setattr(pathsetup, "_windows_bin_dir", lambda: fake_bin_dir)
    monkeypatch.setattr(pathsetup, "_read_user_path_windows", lambda: f"C:\\Other;{fake_bin_dir};C:\\Another")
    written = {}
    monkeypatch.setattr(pathsetup, "_write_user_path_windows", lambda value: written.setdefault("value", value))
    monkeypatch.setattr(pathsetup, "_broadcast_environment_change", lambda: None)

    pathsetup._remove_windows()

    assert not (fake_bin_dir / "rona.cmd").is_file()
    assert not fake_bin_dir.is_dir()  # emptied dir is cleaned up too
    assert written["value"] == "C:\\Other;C:\\Another"
    assert "kaldırıldı" in capsys.readouterr().out


def test_remove_windows_leaves_unrelated_path_entries_alone(tmp_path, monkeypatch):
    fake_bin_dir = tmp_path / "bin"
    fake_bin_dir.mkdir()
    monkeypatch.setattr(pathsetup, "_windows_bin_dir", lambda: fake_bin_dir)
    monkeypatch.setattr(pathsetup, "_read_user_path_windows", lambda: "C:\\Only\\Other")
    write_calls = []
    monkeypatch.setattr(pathsetup, "_write_user_path_windows", lambda value: write_calls.append(value))

    pathsetup._remove_windows()

    assert write_calls == []  # nothing to remove -- must not touch PATH at all


def test_remove_posix_deletes_shim_and_confirmed_rc_block(tmp_path, monkeypatch, capsys):
    fake_bin_dir = tmp_path / "home" / ".local" / "bin"
    fake_bin_dir.mkdir(parents=True)
    (fake_bin_dir / "rona").write_text("#!/usr/bin/env bash\n", encoding="utf-8")
    rc_file = tmp_path / "home" / ".profile"
    rc_file.write_text(
        'export SOMETHING=1\n\n# Added by the Rona installer\nexport PATH="$HOME/.local/bin:$PATH"\n',
        encoding="utf-8",
    )
    monkeypatch.setattr(pathsetup, "_posix_bin_dir", lambda: fake_bin_dir)
    monkeypatch.setattr(pathsetup, "_rc_file_for_shell", lambda: rc_file)
    monkeypatch.setattr(pathsetup.ui, "confirm", lambda *a, **k: True)

    pathsetup._remove_posix(auto_yes=False)

    assert not (fake_bin_dir / "rona").is_file()
    content = rc_file.read_text(encoding="utf-8")
    assert "Added by the Rona installer" not in content
    assert "export SOMETHING=1" in content  # unrelated lines survive
    assert "kaldırıldı" in capsys.readouterr().out


def test_remove_posix_declines_rc_edit_leaves_it_untouched(tmp_path, monkeypatch):
    fake_bin_dir = tmp_path / "home" / ".local" / "bin"
    fake_bin_dir.mkdir(parents=True)
    rc_file = tmp_path / "home" / ".profile"
    original = '# Added by the Rona installer\nexport PATH="$HOME/.local/bin:$PATH"\n'
    rc_file.write_text(original, encoding="utf-8")
    monkeypatch.setattr(pathsetup, "_posix_bin_dir", lambda: fake_bin_dir)
    monkeypatch.setattr(pathsetup, "_rc_file_for_shell", lambda: rc_file)
    monkeypatch.setattr(pathsetup.ui, "confirm", lambda *a, **k: False)

    pathsetup._remove_posix(auto_yes=False)

    assert rc_file.read_text(encoding="utf-8") == original


def test_remove_posix_auto_yes_skips_confirmation(tmp_path, monkeypatch):
    fake_bin_dir = tmp_path / "home" / ".local" / "bin"
    fake_bin_dir.mkdir(parents=True)
    rc_file = tmp_path / "home" / ".profile"
    rc_file.write_text(
        '\n# Added by the Rona installer\nexport PATH="$HOME/.local/bin:$PATH"\n', encoding="utf-8"
    )
    monkeypatch.setattr(pathsetup, "_posix_bin_dir", lambda: fake_bin_dir)
    monkeypatch.setattr(pathsetup, "_rc_file_for_shell", lambda: rc_file)

    def _fail_if_called(*a, **k):
        raise AssertionError("confirm() should not be called when auto_yes=True")

    monkeypatch.setattr(pathsetup.ui, "confirm", _fail_if_called)

    pathsetup._remove_posix(auto_yes=True)

    assert "Added by the Rona installer" not in rc_file.read_text(encoding="utf-8")


def test_remove_posix_no_rc_block_present_is_a_noop(tmp_path, monkeypatch):
    fake_bin_dir = tmp_path / "home" / ".local" / "bin"
    fake_bin_dir.mkdir(parents=True)
    rc_file = tmp_path / "home" / ".profile"
    original = "export SOMETHING=1\n"
    rc_file.write_text(original, encoding="utf-8")
    monkeypatch.setattr(pathsetup, "_posix_bin_dir", lambda: fake_bin_dir)
    monkeypatch.setattr(pathsetup, "_rc_file_for_shell", lambda: rc_file)

    def _fail_if_called(*a, **k):
        raise AssertionError("confirm() should not be called when there's nothing to remove")

    monkeypatch.setattr(pathsetup.ui, "confirm", _fail_if_called)

    pathsetup._remove_posix(auto_yes=False)

    assert rc_file.read_text(encoding="utf-8") == original


def test_remove_posix_missing_shim_and_rc_file_is_a_noop(tmp_path, monkeypatch):
    fake_bin_dir = tmp_path / "home" / ".local" / "bin"
    fake_bin_dir.mkdir(parents=True)
    monkeypatch.setattr(pathsetup, "_posix_bin_dir", lambda: fake_bin_dir)
    monkeypatch.setattr(pathsetup, "_rc_file_for_shell", lambda: tmp_path / "home" / ".profile")

    pathsetup._remove_posix(auto_yes=True)  # must not raise
