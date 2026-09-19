from installer import detect


def _make_root(tmp_path, *, cli=False, backend=False, web=False):
    root = tmp_path / "rona-checkout"
    for name in ("cli", "backend", "web-client"):
        (root / name).mkdir(parents=True)

    if cli:
        venv_python = detect.venv_python_path(root / "cli" / ".venv")
        venv_python.parent.mkdir(parents=True)
        venv_python.write_text("", encoding="utf-8")

    if backend:
        venv_python = detect.venv_python_path(root / "backend" / ".venv")
        venv_python.parent.mkdir(parents=True)
        venv_python.write_text("", encoding="utf-8")
        (root / "backend" / ".env").write_text("", encoding="utf-8")

    if web:
        venv_python = detect.venv_python_path(root / "web-client" / ".venv")
        venv_python.parent.mkdir(parents=True)
        venv_python.write_text("", encoding="utf-8")
        (root / "web-client" / ".env").write_text("", encoding="utf-8")
        dist_index = root / "web-client" / "webui" / "dist" / "index.html"
        dist_index.parent.mkdir(parents=True)
        dist_index.write_text("<html></html>", encoding="utf-8")

    return root


def test_detect_os_returns_a_known_value():
    assert detect.detect_os() in ("windows", "macos", "linux")


def test_python_version_matches_running_interpreter():
    import sys

    assert detect.python_version() == sys.version_info[:3]


def test_package_manager_windows_uses_winget(monkeypatch):
    monkeypatch.setattr(detect.shutil, "which", lambda name: "/x/winget" if name == "winget" else None)
    assert detect.package_manager("windows") == "winget"


def test_package_manager_windows_missing_winget(monkeypatch):
    monkeypatch.setattr(detect.shutil, "which", lambda name: None)
    assert detect.package_manager("windows") is None


def test_package_manager_macos_uses_brew(monkeypatch):
    monkeypatch.setattr(detect.shutil, "which", lambda name: "/x/brew" if name == "brew" else None)
    assert detect.package_manager("macos") == "brew"


def test_package_manager_linux_prefers_apt_then_dnf_then_pacman(monkeypatch):
    monkeypatch.setattr(detect.shutil, "which", lambda name: "/x/apt-get" if name == "apt-get" else None)
    assert detect.package_manager("linux") == "apt-get"

    monkeypatch.setattr(detect.shutil, "which", lambda name: "/x/dnf" if name == "dnf" else None)
    assert detect.package_manager("linux") == "dnf"

    monkeypatch.setattr(detect.shutil, "which", lambda name: None)
    assert detect.package_manager("linux") is None


def test_node_version_parses_v_prefixed_output(monkeypatch):
    monkeypatch.setattr(detect.shutil, "which", lambda name: "/x/node" if name == "node" else None)
    monkeypatch.setattr(detect, "_run_text", lambda cmd: "v20.11.1")
    assert detect.node_version() == (20, 11, 1)


def test_node_version_none_when_node_missing(monkeypatch):
    monkeypatch.setattr(detect.shutil, "which", lambda name: None)
    assert detect.node_version() is None


def test_git_available_reflects_which(monkeypatch):
    monkeypatch.setattr(detect.shutil, "which", lambda name: "/x/git" if name == "git" else None)
    assert detect.git_available() is True
    monkeypatch.setattr(detect.shutil, "which", lambda name: None)
    assert detect.git_available() is False


def test_installed_components_all_false_on_fresh_checkout(tmp_path):
    root = _make_root(tmp_path)
    installed = detect.InstalledComponents(root)
    assert installed.as_dict() == {"cli": False, "backend": False, "web": False}


def test_installed_components_detects_each_independently(tmp_path):
    root = _make_root(tmp_path, cli=True, backend=True, web=True)
    installed = detect.InstalledComponents(root)
    assert installed.as_dict() == {"cli": True, "backend": True, "web": True}


def test_installed_components_backend_requires_both_venv_and_env(tmp_path):
    root = _make_root(tmp_path)
    venv_python = detect.venv_python_path(root / "backend" / ".venv")
    venv_python.parent.mkdir(parents=True)
    venv_python.write_text("", encoding="utf-8")
    # .env deliberately missing
    installed = detect.InstalledComponents(root)
    assert installed.backend is False


def test_installed_components_web_requires_built_dist(tmp_path):
    root = _make_root(tmp_path)
    venv_python = detect.venv_python_path(root / "web-client" / ".venv")
    venv_python.parent.mkdir(parents=True)
    venv_python.write_text("", encoding="utf-8")
    (root / "web-client" / ".env").write_text("", encoding="utf-8")
    # dist/index.html deliberately missing
    installed = detect.InstalledComponents(root)
    assert installed.web is False
