from pathlib import Path
from types import SimpleNamespace

from rona_cli import procutil

BACKEND = Path("/srv/rona/backend")


def _run_returning(monkeypatch, stdout="", returncode=0, record=None):
    def _run(cmd, **kwargs):
        if record is not None:
            record.append(cmd)
        return SimpleNamespace(returncode=returncode, stdout=stdout, stderr="")

    monkeypatch.setattr(procutil.subprocess, "run", _run)


# -- pid_alive (Windows tasklist CSV) ---------------------------------------


def test_tasklist_pid_must_match_exactly():
    row = '"python.exe","1234","Console","1","12,000 K"'
    assert procutil._tasklist_has_pid(row, 12) is False
    assert procutil._tasklist_has_pid(row, 1234) is True


def test_tasklist_no_tasks_info_line_is_not_alive():
    assert procutil._tasklist_has_pid("INFO: No tasks are running which match.", 12) is False


def test_pid_alive_windows_uses_csv_output(monkeypatch):
    calls = []
    monkeypatch.setattr(procutil.os, "name", "nt")
    _run_returning(monkeypatch, '"python.exe","1234","Console","1","12 K"\n', record=calls)
    assert procutil.pid_alive(12) is False
    assert procutil.pid_alive(1234) is True
    assert "CSV" in calls[0]


# -- find_pid_by_port ---------------------------------------------------------


def test_find_pid_by_port_lsof_listens_only(monkeypatch):
    calls = []
    monkeypatch.setattr(procutil.os, "name", "posix")
    _run_returning(monkeypatch, "55\n66\n", record=calls)
    assert procutil.find_pid_by_port("127.0.0.1", 8000) == 55
    assert "-sTCP:LISTEN" in calls[0]
    assert "-iTCP:8000" in calls[0]


NETSTAT = """
  Proto  Local Address          Foreign Address        State           PID
  TCP    0.0.0.0:80             0.0.0.0:0              LISTENING       111
  TCP    127.0.0.1:50000        127.0.0.1:8000         ESTABLISHED     222
  TCP    127.0.0.1:8000         127.0.0.1:50000        ESTABLISHED     333
  TCP    0.0.0.0:80000          0.0.0.0:0              LISTENING       444
  TCP    [::]:8000              [::]:0                 LISTENING       555
"""


def test_netstat_accepts_only_listening_exact_port():
    assert procutil._netstat_listener_pid(NETSTAT, 8000) == 555
    assert procutil._netstat_listener_pid(NETSTAT, 80) == 111
    assert procutil._netstat_listener_pid(NETSTAT, 800) is None


def test_netstat_ignores_established_only():
    only_established = "  TCP    127.0.0.1:8000   127.0.0.1:50000   ESTABLISHED   333\n"
    assert procutil._netstat_listener_pid(only_established, 8000) is None


# -- is_rona_backend ----------------------------------------------------------


def _linux(monkeypatch, cmdline, cwd=None, error=False):
    monkeypatch.setattr(procutil.sys, "platform", "linux")

    def _cmd(pid):
        if error:
            raise procutil.VerifyError("denied")
        return cmdline

    monkeypatch.setattr(procutil, "_read_proc_cmdline", _cmd)
    monkeypatch.setattr(procutil, "_read_proc_cwd", lambda pid: cwd)


def test_linux_run_py_with_matching_cwd(monkeypatch):
    _linux(monkeypatch, "/srv/rona/backend/.venv/bin/python run.py", cwd="/srv/rona/backend")
    assert procutil.is_rona_backend(10, BACKEND) is True


def test_linux_uvicorn_app_main_with_matching_cwd(monkeypatch):
    _linux(monkeypatch, "python -m uvicorn app.main:app --port 8000", cwd="/srv/rona/backend")
    assert procutil.is_rona_backend(10, BACKEND) is True


def test_linux_other_checkout_run_py_is_rejected(monkeypatch):
    _linux(monkeypatch, "python run.py", cwd="/home/me/other-project")
    assert procutil.is_rona_backend(10, BACKEND) is False


def test_linux_command_line_path_ties_to_backend(monkeypatch):
    _linux(monkeypatch, "/srv/rona/backend/.venv/bin/python /srv/rona/backend/run.py", cwd=None)
    assert procutil.is_rona_backend(10, BACKEND) is True


def test_linux_unrelated_process_is_rejected(monkeypatch):
    _linux(monkeypatch, "nginx: master process", cwd="/srv/rona/backend")
    assert procutil.is_rona_backend(10, BACKEND) is False


def test_verification_failure_returns_false(monkeypatch):
    _linux(monkeypatch, "", error=True)
    assert procutil.is_rona_backend(10, BACKEND) is False


def test_windows_command_line(monkeypatch):
    monkeypatch.setattr(procutil.sys, "platform", "win32")
    backend = Path("D:/rona/backend")
    monkeypatch.setattr(
        procutil,
        "_windows_cmdline",
        lambda pid: r'"D:\rona\backend\.venv\Scripts\python.exe" run.py',
    )
    assert procutil.is_rona_backend(10, backend) is True
    monkeypatch.setattr(procutil, "_windows_cmdline", lambda pid: "python.exe run.py")
    assert procutil.is_rona_backend(10, backend) is False


def test_windows_falls_back_to_wmic(monkeypatch):
    monkeypatch.setattr(procutil.sys, "platform", "win32")
    calls = []

    def _run(cmd, **kwargs):
        calls.append(cmd[0])
        if cmd[0] == "powershell":
            raise FileNotFoundError
        return SimpleNamespace(returncode=0, stdout="CommandLine=python run.py\r\n", stderr="")

    monkeypatch.setattr(procutil.subprocess, "run", _run)
    assert procutil._windows_cmdline(10) == "python run.py"
    assert calls == ["powershell", "wmic"]


def test_windows_tools_missing_returns_false(monkeypatch):
    monkeypatch.setattr(procutil.sys, "platform", "win32")

    def _run(cmd, **kwargs):
        raise FileNotFoundError

    monkeypatch.setattr(procutil.subprocess, "run", _run)
    assert procutil.is_rona_backend(10, BACKEND) is False


def test_macos_uses_ps(monkeypatch):
    monkeypatch.setattr(procutil.sys, "platform", "darwin")
    outputs = {
        "ps": "/srv/rona/backend/.venv/bin/python run.py",
        "lsof": "p10\nn/srv/rona/backend\n",
    }

    def _run(cmd, **kwargs):
        return SimpleNamespace(returncode=0, stdout=outputs[cmd[0]], stderr="")

    monkeypatch.setattr(procutil.subprocess, "run", _run)
    assert procutil.is_rona_backend(10, BACKEND) is True


# -- kill_tree (POSIX group logic) ---------------------------------------------


def _posix_signals(monkeypatch, pgid_of):
    sent = []
    monkeypatch.setattr(procutil.os, "name", "posix")
    monkeypatch.setattr(procutil.os, "getpgid", pgid_of, raising=False)
    monkeypatch.setattr(
        procutil.os, "killpg", lambda g, s: sent.append(("pg", g, s)), raising=False
    )
    monkeypatch.setattr(procutil.os, "kill", lambda p, s: sent.append(("pid", p, s)))
    return sent


def test_kill_tree_uses_killpg_only_for_group_leader(monkeypatch):
    sent = _posix_signals(monkeypatch, lambda pid: pid)
    procutil.kill_tree(50)
    assert sent == [("pg", 50, procutil.signal.SIGTERM)]


def test_kill_tree_signals_single_pid_when_not_group_leader(monkeypatch):
    sent = _posix_signals(monkeypatch, lambda pid: 1)
    procutil.kill_tree(50)
    assert sent == [("pid", 50, procutil.signal.SIGTERM)]


def test_kill_tree_ignores_vanished_process(monkeypatch):
    def _gone(pid):
        raise ProcessLookupError

    _posix_signals(monkeypatch, _gone)
    procutil.kill_tree(50)


def test_netstat_listener_is_found_in_localized_output():
    # State names are localized; only the "no peer" foreign address is stable.
    turkish = (
        "  TCP    0.0.0.0:8000           0.0.0.0:0              DİNLENİYOR      901\n"
        "  TCP    127.0.0.1:8000         127.0.0.1:50000        KURULDU         902\n"
    ).replace("\n", "\n")
    german = "  TCP    [::]:8000              [::]:0                 ABHÖREN         903\n"
    english = "  TCP    0.0.0.0:8000           0.0.0.0:0              LISTENING       904\n"
    assert procutil._netstat_listener_pid(turkish, 8000) == 901
    assert procutil._netstat_listener_pid(german, 8000) == 903
    assert procutil._netstat_listener_pid(english, 8000) == 904
    assert procutil._netstat_listener_pid(turkish, 800) is None


def test_netstat_established_row_ignored_in_any_language():
    row = "  TCP    127.0.0.1:8000         127.0.0.1:50000        KURULDU         902\n"
    assert procutil._netstat_listener_pid(row, 8000) is None
