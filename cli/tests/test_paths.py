import json
import os

import pytest

from rona_cli import paths


def _make_root(tmp_path):
    root = tmp_path / "rona-checkout"
    (root / "backend").mkdir(parents=True)
    (root / "web-client").mkdir(parents=True)
    return root


def _isolate_file_based_lookup(monkeypatch, tmp_path):
    """Make step 3 (upward search from paths.py's own location) a dead end.

    Without this, `find_root()` run from inside this very repo's checkout
    would always find the REAL root via `__file__` before ever reaching the
    cwd-based fallback (step 4) or correctly failing -- tests that need to
    exercise those paths patch `__file__` to somewhere under `tmp_path`
    instead, which has no `backend/`/`web-client/` ancestors.
    """
    dead_end = tmp_path / "isolated" / "rona_cli"
    dead_end.mkdir(parents=True)
    monkeypatch.setattr(paths, "__file__", str(dead_end / "paths.py"))


def test_explicit_root_is_used_when_it_looks_like_an_installation(tmp_path):
    root = _make_root(tmp_path)
    assert paths.find_root(str(root)) == root.resolve()


def test_explicit_root_that_is_not_an_installation_raises(tmp_path):
    not_root = tmp_path / "not-rona"
    not_root.mkdir()
    with pytest.raises(paths.RonaNotFoundError):
        paths.find_root(str(not_root))


def test_env_var_is_used_when_no_explicit_root_given(tmp_path, monkeypatch):
    root = _make_root(tmp_path)
    monkeypatch.setenv("RONA_HOME", str(root))
    assert paths.find_root(None) == root.resolve()


def test_state_file_is_used_when_no_env_var(tmp_path, monkeypatch):
    root = _make_root(tmp_path)
    monkeypatch.delenv("RONA_HOME", raising=False)
    state_path = tmp_path / "home" / ".rona" / "config.json"
    state_path.parent.mkdir(parents=True)
    state_path.write_text(json.dumps({"root": str(root)}), encoding="utf-8")
    monkeypatch.setattr(paths, "state_file", lambda: state_path)
    assert paths.find_root(None) == root.resolve()


def test_upward_search_from_cwd_finds_installation(tmp_path, monkeypatch):
    root = _make_root(tmp_path)
    nested = root / "some" / "deep" / "dir"
    nested.mkdir(parents=True)
    monkeypatch.delenv("RONA_HOME", raising=False)
    monkeypatch.setattr(paths, "state_file", lambda: tmp_path / "no-such-state.json")
    _isolate_file_based_lookup(monkeypatch, tmp_path)
    monkeypatch.chdir(nested)
    assert paths.find_root(None) == root.resolve()


def test_nothing_found_raises_with_a_helpful_message(tmp_path, monkeypatch):
    monkeypatch.delenv("RONA_HOME", raising=False)
    monkeypatch.setattr(paths, "state_file", lambda: tmp_path / "no-such-state.json")
    _isolate_file_based_lookup(monkeypatch, tmp_path)
    isolated_cwd = tmp_path / "empty"
    isolated_cwd.mkdir()
    monkeypatch.chdir(isolated_cwd)
    with pytest.raises(paths.RonaNotFoundError, match="bulunamadı"):
        paths.find_root(None)


def test_rona_paths_derives_component_paths(tmp_path):
    root = _make_root(tmp_path)
    p = paths.RonaPaths(root)
    assert p.backend_dir == root / "backend"
    assert p.web_dir == root / "web-client"
    assert p.backend_env == root / "backend" / ".env"
    assert p.web_env == root / "web-client" / ".env"
    assert p.backend_pid == root / "backend" / "rona.pid"
    assert p.installed_packages_lockfile == (
        root / "backend" / "toolbox" / "custom" / "installed.json"
    )


def test_backend_python_raises_when_venv_missing(tmp_path):
    root = _make_root(tmp_path)
    p = paths.RonaPaths(root)
    with pytest.raises(paths.RonaNotFoundError):
        p.backend_python()


def test_backend_python_finds_venv_interpreter(tmp_path):
    root = _make_root(tmp_path)
    venv_dir = root / "backend" / ".venv"
    if os.name == "nt":
        python_path = venv_dir / "Scripts" / "python.exe"
    else:
        python_path = venv_dir / "bin" / "python"
    python_path.parent.mkdir(parents=True)
    python_path.write_text("", encoding="utf-8")
    p = paths.RonaPaths(root)
    assert p.backend_python() == python_path
