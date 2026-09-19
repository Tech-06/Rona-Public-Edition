import json
from types import SimpleNamespace

from rona_cli.commands.edit import memory as edit_memory

from .helpers import make_root


def _write_backend_env(root, port, token="test-token"):
    (root / "backend" / ".env").write_text(
        f"AUTH_TOKEN={token}\nPORT={port}\nHOST=127.0.0.1\n", encoding="utf-8"
    )


def _args(root, **overrides):
    defaults = {
        "root": str(root),
        "json": False,
        "query": None,
        "person": None,
        "date_from": None,
        "date_to": None,
        "limit": 10,
        "content": None,
        "layer": None,
        "metadata": None,
        "id": None,
        "yes": False,
    }
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


def test_search_prints_results(tmp_path, fake_api, capsys):
    root = make_root(tmp_path)
    _write_backend_env(root, fake_api.port)
    fake_api.set_route(
        "GET",
        "/api/data/memories/search",
        200,
        {"success": True, "results": [{"id": 1, "layer": "short", "content": "x", "score": 0.9}]},
    )
    code = edit_memory._cmd_search(_args(root, query="x"))
    assert code == 0
    out = capsys.readouterr().out
    assert "x" in out
    request = fake_api.requests[0]
    assert request["path"].startswith("/api/data/memories/search?")
    assert "q=x" in request["path"]


def test_search_json_mode_prints_raw_payload(tmp_path, fake_api, capsys):
    root = make_root(tmp_path)
    _write_backend_env(root, fake_api.port)
    fake_api.set_route(
        "GET", "/api/data/memories/search", 200, {"success": True, "results": []}
    )
    code = edit_memory._cmd_search(_args(root, query="x", json=True))
    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload == {"success": True, "results": []}


def test_add_posts_content_and_prints_id(tmp_path, fake_api, capsys):
    root = make_root(tmp_path)
    _write_backend_env(root, fake_api.port)
    fake_api.set_route(
        "POST", "/api/data/memories", 200, {"success": True, "id": 7, "message": "ok"}
    )
    code = edit_memory._cmd_add(_args(root, content="loves tea", layer="short"))
    assert code == 0
    assert fake_api.requests[0]["body"] == {
        "layer": "short",
        "content": "loves tea",
        "person_id": None,
        "metadata": None,
    }
    assert "7" in capsys.readouterr().out


def test_add_invalid_metadata_json_fails_without_request(tmp_path, fake_api):
    root = make_root(tmp_path)
    _write_backend_env(root, fake_api.port)
    code = edit_memory._cmd_add(
        _args(root, content="x", layer="short", metadata="not-json")
    )
    assert code == 1
    assert fake_api.requests == []


def test_edit_requires_at_least_one_field(tmp_path, fake_api):
    root = make_root(tmp_path)
    _write_backend_env(root, fake_api.port)
    code = edit_memory._cmd_edit(_args(root, id=1))
    assert code == 1
    assert fake_api.requests == []


def test_edit_sends_only_given_fields(tmp_path, fake_api):
    root = make_root(tmp_path)
    _write_backend_env(root, fake_api.port)
    fake_api.set_route("PUT", "/api/data/memories/1", 200, {"success": True})
    code = edit_memory._cmd_edit(_args(root, id=1, content="new"))
    assert code == 0
    assert fake_api.requests[0]["body"] == {"content": "new"}


def test_delete_asks_for_confirmation_and_aborts_on_no(tmp_path, fake_api, monkeypatch):
    root = make_root(tmp_path)
    _write_backend_env(root, fake_api.port)
    monkeypatch.setattr(edit_memory.ui, "confirm", lambda *a, **k: False)
    code = edit_memory._cmd_delete(_args(root, id=1))
    assert code == 1
    assert fake_api.requests == []


def test_delete_yes_flag_skips_confirmation(tmp_path, fake_api):
    root = make_root(tmp_path)
    _write_backend_env(root, fake_api.port)
    fake_api.set_route("DELETE", "/api/data/memories/1", 200, {"success": True})
    code = edit_memory._cmd_delete(_args(root, id=1, yes=True))
    assert code == 0
    assert fake_api.requests[0]["method"] == "DELETE"


def test_stats_prints_summary(tmp_path, fake_api, capsys):
    root = make_root(tmp_path)
    _write_backend_env(root, fake_api.port)
    fake_api.set_route(
        "GET",
        "/api/data/memories/stats",
        200,
        {
            "success": True,
            "total": 3,
            "by_layer": {"deep": 1, "seasonal": 0, "short": 2},
            "general_count": 2,
            "person_linked_count": 1,
            "oldest_created_at": "2026-01-01T00:00:00Z",
            "newest_created_at": "2026-01-02T00:00:00Z",
            "total_access_count": 5,
        },
    )
    code = edit_memory._cmd_stats(_args(root))
    assert code == 0
    out = capsys.readouterr().out
    assert "Toplam: 3" in out


def test_backend_unreachable_reports_error(tmp_path, capsys):
    root = make_root(tmp_path)
    (root / "backend" / ".env").write_text("", encoding="utf-8")  # no AUTH_TOKEN
    code = edit_memory._cmd_stats(_args(root))
    assert code == 1
