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
        "offset": 0,
        "content": None,
        "layer": None,
        "metadata": None,
        "id": None,
        "archive_id": None,
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


def test_stats_prints_archive_and_consolidation_fields_when_present(tmp_path, fake_api, capsys):
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
            "archived_count": 4,
            "last_consolidation": {
                "id": 1,
                "triggered_by": "manual",
                "started_at": "2026-01-03T00:00:00Z",
                "finished_at": "2026-01-03T00:00:05Z",
                "promoted_short": 2,
                "promoted_seasonal": 1,
                "archived": 3,
                "deleted": 0,
                "error": None,
            },
        },
    )
    code = edit_memory._cmd_stats(_args(root))
    assert code == 0
    out = capsys.readouterr().out
    assert "Arşivdeki anı: 4" in out
    assert "Son konsolidasyon: 2026-01-03T00:00:05Z (manual)" in out
    assert "terfi: 2+1, arşiv: 3, silinen: 0" in out


def test_stats_prints_no_consolidation_yet_when_key_present_but_null(tmp_path, fake_api, capsys):
    root = make_root(tmp_path)
    _write_backend_env(root, fake_api.port)
    fake_api.set_route(
        "GET",
        "/api/data/memories/stats",
        200,
        {
            "success": True,
            "total": 0,
            "by_layer": {"deep": 0, "seasonal": 0, "short": 0},
            "general_count": 0,
            "person_linked_count": 0,
            "oldest_created_at": None,
            "newest_created_at": None,
            "total_access_count": 0,
            "archived_count": 0,
            "last_consolidation": None,
        },
    )
    code = edit_memory._cmd_stats(_args(root))
    assert code == 0
    out = capsys.readouterr().out
    assert "Henüz konsolidasyon çalışmadı." in out


def test_stats_omits_archive_fields_on_old_backend_payload(tmp_path, fake_api, capsys):
    # Same payload shape the pre-existing test_stats_prints_summary uses,
    # without archived_count/last_consolidation -- an older backend must
    # not crash the CLI.
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
    assert "Arşivdeki anı" not in out
    assert "konsolidasyon" not in out.lower()


def test_list_sends_default_person_all_and_prints_line(tmp_path, fake_api, capsys):
    root = make_root(tmp_path)
    _write_backend_env(root, fake_api.port)
    fake_api.set_route(
        "GET",
        "/api/data/memories",
        200,
        {
            "success": True,
            "total": 1,
            "memories": [
                {
                    "id": 5,
                    "person_id": None,
                    "layer": "short",
                    "content": "loves tea",
                    "created_at": "2026-01-01T00:00:00Z",
                    "metadata": {},
                    "access_count": 4,
                    "layer_hits": 2,
                    "layer_since": "2026-01-01T00:00:00Z",
                    "last_accessed": None,
                }
            ],
        },
    )
    code = edit_memory._cmd_list(_args(root, person="all", limit=50))
    assert code == 0
    request = fake_api.requests[0]
    assert request["path"].startswith("/api/data/memories?")
    assert "person=all" in request["path"]
    out = capsys.readouterr().out
    assert "[5]" in out
    assert "erişim 2/4" in out
    assert "hiç" in out
    assert "loves tea" in out
    assert "1/1 anı gösteriliyor" in out


def test_list_empty_prints_no_memories_message(tmp_path, fake_api, capsys):
    root = make_root(tmp_path)
    _write_backend_env(root, fake_api.port)
    fake_api.set_route(
        "GET", "/api/data/memories", 200, {"success": True, "total": 0, "memories": []}
    )
    code = edit_memory._cmd_list(_args(root, person="all", limit=50))
    assert code == 0
    assert "Anı yok." in capsys.readouterr().out


def test_archive_posts_and_prints_confirmation(tmp_path, fake_api, capsys):
    root = make_root(tmp_path)
    _write_backend_env(root, fake_api.port)
    fake_api.set_route(
        "POST", "/api/data/memories/5/archive", 200, {"success": True, "archive_id": 9}
    )
    code = edit_memory._cmd_archive(_args(root, id=5))
    assert code == 0
    assert fake_api.requests[0]["method"] == "POST"
    out = capsys.readouterr().out
    assert "#5" in out
    assert "#9" in out


def test_archived_prints_reason_labels(tmp_path, fake_api, capsys):
    root = make_root(tmp_path)
    _write_backend_env(root, fake_api.port)
    fake_api.set_route(
        "GET",
        "/api/data/archive",
        200,
        {
            "success": True,
            "total": 3,
            "archive": [
                {
                    "id": 1,
                    "memory_id": 10,
                    "person_id": None,
                    "layer": "seasonal",
                    "content": "old fact",
                    "access_count": 1,
                    "created_at": "2026-01-01T00:00:00Z",
                    "last_accessed": None,
                    "metadata": {},
                    "archived_at": "2026-02-01T00:00:00Z",
                    "reason": "auto",
                },
                {
                    "id": 2,
                    "memory_id": 11,
                    "person_id": None,
                    "layer": "short",
                    "content": "manual pick",
                    "access_count": 0,
                    "created_at": "2026-01-01T00:00:00Z",
                    "last_accessed": None,
                    "metadata": {},
                    "archived_at": "2026-02-01T00:00:00Z",
                    "reason": "manual",
                },
                {
                    "id": 3,
                    "memory_id": 12,
                    "person_id": 7,
                    "layer": "deep",
                    "content": "linked fact",
                    "access_count": 2,
                    "created_at": "2026-01-01T00:00:00Z",
                    "last_accessed": None,
                    "metadata": {},
                    "archived_at": "2026-02-01T00:00:00Z",
                    "reason": "person_deleted",
                },
            ],
        },
    )
    code = edit_memory._cmd_archived(_args(root))
    assert code == 0
    out = capsys.readouterr().out
    assert "otomatik" in out
    assert "elle" in out
    assert "kişi silindi" in out


def test_archived_empty_prints_message(tmp_path, fake_api, capsys):
    root = make_root(tmp_path)
    _write_backend_env(root, fake_api.port)
    fake_api.set_route(
        "GET", "/api/data/archive", 200, {"success": True, "total": 0, "archive": []}
    )
    code = edit_memory._cmd_archived(_args(root))
    assert code == 0
    assert "Arşiv boş." in capsys.readouterr().out


def test_restore_posts_and_prints_confirmation(tmp_path, fake_api, capsys):
    root = make_root(tmp_path)
    _write_backend_env(root, fake_api.port)
    fake_api.set_route(
        "POST", "/api/data/archive/2/restore", 200, {"success": True, "memory_id": 10}
    )
    code = edit_memory._cmd_restore(_args(root, archive_id=2))
    assert code == 0
    assert fake_api.requests[0]["method"] == "POST"
    out = capsys.readouterr().out
    assert "#2" in out
    assert "10" in out


def test_purge_asks_for_confirmation_and_aborts_on_no(tmp_path, fake_api, monkeypatch):
    root = make_root(tmp_path)
    _write_backend_env(root, fake_api.port)
    monkeypatch.setattr(edit_memory.ui, "confirm", lambda *a, **k: False)
    code = edit_memory._cmd_purge(_args(root, archive_id=2))
    assert code == 1
    assert fake_api.requests == []


def test_purge_yes_flag_skips_confirmation_and_deletes(tmp_path, fake_api):
    root = make_root(tmp_path)
    _write_backend_env(root, fake_api.port)
    fake_api.set_route("DELETE", "/api/data/archive/2", 200, {"success": True})
    code = edit_memory._cmd_purge(_args(root, archive_id=2, yes=True))
    assert code == 0
    assert fake_api.requests[0]["method"] == "DELETE"
