from types import SimpleNamespace

from installer import prereq


def test_install_command_windows_uses_winget_id():
    command = prereq.install_command("windows", None, "node")
    assert command == ["winget", "install", "--id", "OpenJS.NodeJS.LTS", "-e", "--source", "winget"]


def test_install_command_macos_uses_brew():
    command = prereq.install_command("macos", None, "git")
    assert command == ["brew", "install", "git"]


def test_install_command_linux_apt():
    command = prereq.install_command("linux", "apt-get", "node")
    assert command == ["sudo", "apt-get", "install", "-y", "nodejs", "npm"]


def test_install_command_linux_dnf():
    command = prereq.install_command("linux", "dnf", "git")
    assert command == ["sudo", "dnf", "install", "-y", "git"]


def test_install_command_linux_pacman():
    command = prereq.install_command("linux", "pacman", "node")
    assert command == ["sudo", "pacman", "-S", "--noconfirm", "nodejs", "npm"]


def test_install_command_none_when_no_package_manager():
    assert prereq.install_command("linux", None, "node") is None


def test_ensure_prerequisite_short_circuits_when_already_available():
    assert prereq.ensure_prerequisite("Node.js", "node", True, "linux", "apt-get", auto_yes=False) is True


def test_ensure_prerequisite_reports_error_when_no_package_manager(capsys):
    result = prereq.ensure_prerequisite("Node.js", "node", False, "linux", None, auto_yes=True)
    assert result is False
    assert "bulunamadı" in capsys.readouterr().err


def test_ensure_prerequisite_asks_for_confirmation_and_aborts_on_no(monkeypatch):
    monkeypatch.setattr(prereq.ui, "confirm", lambda *a, **k: False)
    result = prereq.ensure_prerequisite("Node.js", "node", False, "linux", "apt-get", auto_yes=False)
    assert result is False


def test_ensure_prerequisite_installs_and_verifies(monkeypatch):
    monkeypatch.setattr(prereq.subprocess, "run", lambda *a, **k: SimpleNamespace(returncode=0))
    monkeypatch.setattr(prereq.shutil, "which", lambda name: "/usr/bin/node")
    result = prereq.ensure_prerequisite("Node.js", "node", False, "linux", "apt-get", auto_yes=True)
    assert result is True


def test_ensure_prerequisite_install_failure_reports_error(monkeypatch, capsys):
    monkeypatch.setattr(prereq.subprocess, "run", lambda *a, **k: SimpleNamespace(returncode=1))
    result = prereq.ensure_prerequisite("Node.js", "node", False, "linux", "apt-get", auto_yes=True)
    assert result is False
    assert "başarısız" in capsys.readouterr().err


def test_ensure_prerequisite_succeeds_but_not_yet_on_path_warns(monkeypatch, capsys):
    monkeypatch.setattr(prereq.subprocess, "run", lambda *a, **k: SimpleNamespace(returncode=0))
    monkeypatch.setattr(prereq.shutil, "which", lambda name: None)
    result = prereq.ensure_prerequisite("Node.js", "node", False, "linux", "apt-get", auto_yes=True)
    assert result is False
