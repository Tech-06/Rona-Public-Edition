from types import SimpleNamespace

from rona_cli.commands import task as task_cmd

from .helpers import make_root


def _write_backend_env(root, port, token="test-token"):
    (root / "backend" / ".env").write_text(
        f"AUTH_TOKEN={token}\nPORT={port}\nHOST=127.0.0.1\n", encoding="utf-8"
    )


def _args(root, **overrides):
    defaults = {
        "root": str(root),
        "json": False,
        "status": "all",
        "limit": 100,
        "id": None,
        "yes": False,
    }
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


def test_list_prints_tasks(tmp_path, fake_api, capsys):
    root = make_root(tmp_path)
    _write_backend_env(root, fake_api.port)
    fake_api.set_route(
        "GET",
        "/api/tasks",
        200,
        {"tasks": [{"id": "t1", "name": "Water plants", "status": "active", "next_run": "later"}]},
    )
    code = task_cmd._cmd_list(_args(root))
    assert code == 0
    out = capsys.readouterr().out
    assert "Water plants" in out
    assert "status=all" in fake_api.requests[0]["path"]


def test_list_empty_prints_hint(tmp_path, fake_api, capsys):
    root = make_root(tmp_path)
    _write_backend_env(root, fake_api.port)
    fake_api.set_route("GET", "/api/tasks", 200, {"tasks": []})
    code = task_cmd._cmd_list(_args(root))
    assert code == 0
    assert "yok" in capsys.readouterr().out


def test_del_confirms_before_deleting(tmp_path, fake_api, monkeypatch):
    root = make_root(tmp_path)
    _write_backend_env(root, fake_api.port)
    monkeypatch.setattr(task_cmd.ui, "confirm", lambda *a, **k: False)
    code = task_cmd._cmd_del(_args(root, id="t1"))
    assert code == 1
    assert fake_api.requests == []


def test_del_yes_flag_deletes(tmp_path, fake_api):
    root = make_root(tmp_path)
    _write_backend_env(root, fake_api.port)
    fake_api.set_route("DELETE", "/api/tasks/t1", 200, {"deleted": True})
    code = task_cmd._cmd_del(_args(root, id="t1", yes=True))
    assert code == 0
    assert fake_api.requests[0]["method"] == "DELETE"


def test_toggle_flips_active_to_passive(tmp_path, fake_api):
    root = make_root(tmp_path)
    _write_backend_env(root, fake_api.port)
    fake_api.set_route("GET", "/api/tasks/t1", 200, {"id": "t1", "status": "active"})
    fake_api.set_route("POST", "/api/tasks/t1/status", 200, {"id": "t1", "status": "passive"})
    code = task_cmd._cmd_toggle(_args(root, id="t1"))
    assert code == 0
    post_request = next(r for r in fake_api.requests if r["method"] == "POST")
    assert post_request["body"] == {"status": "passive"}


def test_toggle_flips_passive_to_active(tmp_path, fake_api):
    root = make_root(tmp_path)
    _write_backend_env(root, fake_api.port)
    fake_api.set_route("GET", "/api/tasks/t1", 200, {"id": "t1", "status": "passive"})
    fake_api.set_route("POST", "/api/tasks/t1/status", 200, {"id": "t1", "status": "active"})
    code = task_cmd._cmd_toggle(_args(root, id="t1"))
    assert code == 0
    post_request = next(r for r in fake_api.requests if r["method"] == "POST")
    assert post_request["body"] == {"status": "active"}


def test_toggle_missing_task_reports_error(tmp_path, fake_api):
    root = make_root(tmp_path)
    _write_backend_env(root, fake_api.port)
    # no route registered for GET /tasks/missing -> 404
    code = task_cmd._cmd_toggle(_args(root, id="missing"))
    assert code == 1
