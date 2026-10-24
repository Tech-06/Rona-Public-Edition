import json
from types import SimpleNamespace

from installer import detect
from installer.steps import backend as backend_step


def _make_backend(tmp_path, with_package=True):
    root = tmp_path / "root"
    backend_dir = root / "backend"
    custom = backend_dir / "toolbox" / "custom"
    custom.mkdir(parents=True)
    (custom / ".manager.lock").write_text("", encoding="utf-8")
    if with_package:
        (custom / "weather").mkdir()
    (backend_dir / ".env.example").write_text("AUTH_TOKEN=\n", encoding="utf-8")
    return root, backend_dir


def _fake_run(calls, *, reinstall_rc=0, verify_rc=0, packages=("weather",)):
    def run(cmd, **kwargs):
        calls.append((list(cmd), kwargs.get("cwd")))
        if "reinstall-deps" in cmd:
            out = json.dumps({"ok": reinstall_rc == 0, "packages": list(packages)})
            return SimpleNamespace(returncode=reinstall_rc, stdout=out, stderr="boom")
        if "verify" in cmd:
            return SimpleNamespace(returncode=verify_rc, stdout="", stderr="")
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    return run


def test_repair_reinstalls_package_deps_then_verifies(tmp_path, monkeypatch):
    root, backend_dir = _make_backend(tmp_path)
    (backend_dir / ".venv").mkdir()
    calls = []
    monkeypatch.setattr(backend_step.subprocess, "run", _fake_run(calls))
    # the fake run never recreates the venv dir, so skip the real delete
    monkeypatch.setattr(backend_step.shutil, "rmtree", lambda p: None)

    assert backend_step.install(root, reinstall=True) is True

    python = str(detect.venv_python_path(backend_dir / ".venv"))
    manager_calls = [(c, cwd) for c, cwd in calls if "toolbox.manager" in c]
    assert manager_calls[0][0] == [python, "-m", "toolbox.manager", "--json", "reinstall-deps"]
    assert manager_calls[1][0] == [python, "-m", "toolbox.manager", "--json", "verify", "weather"]
    assert len(manager_calls) == 2
    assert all(cwd == backend_dir for _, cwd in manager_calls)
    # requirements.txt goes in before the packages' own deps
    first_requirements = next(i for i, (c, _) in enumerate(calls) if "-r" in c)
    first_manager = next(i for i, (c, _) in enumerate(calls) if "toolbox.manager" in c)
    assert first_requirements < first_manager


def test_no_packages_means_no_manager_calls(tmp_path, monkeypatch):
    root, _ = _make_backend(tmp_path, with_package=False)
    calls = []
    monkeypatch.setattr(backend_step.subprocess, "run", _fake_run(calls))

    assert backend_step.install(root, reinstall=False) is True
    assert not [c for c, _ in calls if "toolbox.manager" in c]


def test_reinstall_deps_failure_is_a_warning_not_fatal(tmp_path, monkeypatch):
    root, _ = _make_backend(tmp_path)
    calls = []
    warnings = []
    monkeypatch.setattr(backend_step.subprocess, "run", _fake_run(calls, reinstall_rc=1))
    monkeypatch.setattr(backend_step.ui, "warn", warnings.append)

    assert backend_step.install(root, reinstall=False) is True

    assert not [c for c, _ in calls if "verify" in c]  # nothing to verify after a failure
    assert any("boom" in w for w in warnings)


def test_unhealthy_package_is_a_warning_not_fatal(tmp_path, monkeypatch):
    root, _ = _make_backend(tmp_path)
    warnings = []
    monkeypatch.setattr(backend_step.subprocess, "run", _fake_run([], verify_rc=1))
    monkeypatch.setattr(backend_step.ui, "warn", warnings.append)

    assert backend_step.install(root, reinstall=False) is True
    assert any("weather" in w for w in warnings)
