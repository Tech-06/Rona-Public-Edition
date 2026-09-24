import json
from types import SimpleNamespace

from rona_cli.commands.edit import memory_consolidate

from .helpers import make_root


def _write_backend_env(root, port, token="test-token"):
    (root / "backend" / ".env").write_text(
        f"AUTH_TOKEN={token}\nPORT={port}\nHOST=127.0.0.1\n", encoding="utf-8"
    )


def _args(root, **overrides):
    defaults = {
        "root": str(root),
        "json": False,
        "dry_run": False,
        "interval_hours": None,
        "auto_promote": None,
        "auto_archive": None,
        "auto_delete": None,
        "short_promote_hits": None,
        "seasonal_promote_hits": None,
        "seasonal_archive_days": None,
        "short_delete_days": None,
        "short_delete_below_hits": None,
        "access_top_n": None,
        "access_cooldown_hours": None,
    }
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


_POLICY = {
    "consolidation_interval_hours": 24,
    "auto_promote_enabled": True,
    "auto_archive_enabled": True,
    "auto_delete_enabled": True,
    "short_promote_hits": 3,
    "seasonal_promote_hits": 10,
    "seasonal_archive_days": 90,
    "short_delete_days": 7,
    "short_delete_below_hits": 3,
    "access_top_n": 3,
    "access_cooldown_hours": 12,
}


def test_run_sends_dry_run_body_and_prints_preview(tmp_path, fake_api, capsys):
    root = make_root(tmp_path)
    _write_backend_env(root, fake_api.port)
    fake_api.set_route(
        "POST",
        "/api/memory/consolidation/run",
        200,
        {
            "dry_run": True,
            "triggered_by": "manual",
            "started_at": "2026-01-01T00:00:00Z",
            "finished_at": "2026-01-01T00:00:01Z",
            "run_id": None,
            "policy": _POLICY,
            "promoted_short": [{"id": 1, "layer": "short", "hits": 3, "preview": "loves tea"}],
            "promoted_seasonal": [],
            "archived": [{"id": 2, "layer": "seasonal", "hits": 0, "preview": "old fact"}],
            "deleted": [{"id": 3, "layer": "short", "hits": 0, "preview": "stale note"}],
            "counts": {"promoted_short": 1, "promoted_seasonal": 0, "archived": 1, "deleted": 1},
        },
    )
    code = memory_consolidate._cmd_run(_args(root, dry_run=True))
    assert code == 0
    assert fake_api.requests[0]["body"] == {"dry_run": True}
    out = capsys.readouterr().out
    assert "Önizleme" in out
    assert "#1 short → seasonal (3 erişim): loves tea" in out
    assert "#2 arşive (seasonal): old fact" in out
    assert "#3 silindi (0 erişim): stale note" in out


def test_run_real_run_prints_done_heading_with_run_id(tmp_path, fake_api, capsys):
    root = make_root(tmp_path)
    _write_backend_env(root, fake_api.port)
    fake_api.set_route(
        "POST",
        "/api/memory/consolidation/run",
        200,
        {
            "dry_run": False,
            "triggered_by": "manual",
            "started_at": "2026-01-01T00:00:00Z",
            "finished_at": "2026-01-01T00:00:01Z",
            "run_id": 7,
            "policy": _POLICY,
            "promoted_short": [],
            "promoted_seasonal": [],
            "archived": [],
            "deleted": [],
            "counts": {"promoted_short": 0, "promoted_seasonal": 0, "archived": 0, "deleted": 0},
        },
    )
    code = memory_consolidate._cmd_run(_args(root, dry_run=False))
    assert code == 0
    assert fake_api.requests[0]["body"] == {"dry_run": False}
    out = capsys.readouterr().out
    assert "çalışma #7" in out
    assert "Değişecek bir şey yok." in out


def test_run_json_mode_prints_raw_payload(tmp_path, fake_api, capsys):
    root = make_root(tmp_path)
    _write_backend_env(root, fake_api.port)
    payload = {
        "dry_run": True,
        "triggered_by": "manual",
        "started_at": "x",
        "finished_at": "y",
        "run_id": None,
        "policy": _POLICY,
        "promoted_short": [],
        "promoted_seasonal": [],
        "archived": [],
        "deleted": [],
        "counts": {"promoted_short": 0, "promoted_seasonal": 0, "archived": 0, "deleted": 0},
    }
    fake_api.set_route("POST", "/api/memory/consolidation/run", 200, payload)
    code = memory_consolidate._cmd_run(_args(root, dry_run=True, json=True))
    assert code == 0
    assert json.loads(capsys.readouterr().out) == payload


def test_run_busy_409_prints_backend_message_and_fails(tmp_path, fake_api, capsys):
    root = make_root(tmp_path)
    _write_backend_env(root, fake_api.port)
    fake_api.set_route(
        "POST",
        "/api/memory/consolidation/run",
        409,
        {"detail": "a memory consolidation run is already in progress"},
    )
    code = memory_consolidate._cmd_run(_args(root, dry_run=False))
    assert code == 1
    assert "already in progress" in capsys.readouterr().err


def test_status_prints_scheduler_policy_and_runs(tmp_path, fake_api, capsys):
    root = make_root(tmp_path)
    _write_backend_env(root, fake_api.port)
    fake_api.set_route(
        "GET",
        "/api/memory/consolidation",
        200,
        {
            "policy": _POLICY,
            "running": False,
            "scheduler": {
                "active": True,
                "interval_hours": 24,
                "next_run_at": "2026-01-02T00:00:00Z",
            },
            "runs": [
                {
                    "id": 1,
                    "triggered_by": "manual",
                    "started_at": "2026-01-01T00:00:00Z",
                    "finished_at": "2026-01-01T00:00:01Z",
                    "promoted_short": 1,
                    "promoted_seasonal": 0,
                    "archived": 0,
                    "deleted": 0,
                    "error": None,
                }
            ],
        },
    )
    code = memory_consolidate._cmd_status(_args(root))
    assert code == 0
    out = capsys.readouterr().out
    assert "aktif" in out
    assert "MEMORY_SHORT_PROMOTE_HITS = 3" in out
    # Every setting is listed, including the ones whose policy key differs
    # from the CLI flag dest (interval + the three on/off switches).
    for env_key in (
        "MEMORY_CONSOLIDATION_INTERVAL_HOURS",
        "MEMORY_AUTO_PROMOTE_ENABLED",
        "MEMORY_AUTO_ARCHIVE_ENABLED",
        "MEMORY_AUTO_DELETE_ENABLED",
    ):
        assert f"{env_key} = " in out
    assert "#1 manual" in out


def test_status_shows_running_flag(tmp_path, fake_api, capsys):
    root = make_root(tmp_path)
    _write_backend_env(root, fake_api.port)
    fake_api.set_route(
        "GET",
        "/api/memory/consolidation",
        200,
        {
            "policy": _POLICY,
            "running": True,
            "scheduler": {"active": False, "interval_hours": 0, "next_run_at": None},
            "runs": [],
        },
    )
    code = memory_consolidate._cmd_status(_args(root))
    assert code == 0
    out = capsys.readouterr().out
    assert "çalışıyor" in out
    assert "kapalı" in out


def test_config_show_json_reports_values_and_defaults(tmp_path, capsys):
    root = make_root(tmp_path)
    (root / "backend" / ".env").write_text(
        "AUTH_TOKEN=x\nMEMORY_SHORT_PROMOTE_HITS=5\n", encoding="utf-8"
    )
    code = memory_consolidate._cmd_config(_args(root, json=True))
    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is True
    assert payload["values"]["MEMORY_SHORT_PROMOTE_HITS"] == "5"
    assert payload["values"]["MEMORY_CONSOLIDATION_INTERVAL_HOURS"] == "24"


def test_config_show_text_marks_default_and_overridden_values(tmp_path, capsys):
    root = make_root(tmp_path)
    (root / "backend" / ".env").write_text(
        "AUTH_TOKEN=x\nMEMORY_SHORT_PROMOTE_HITS=5\n", encoding="utf-8"
    )
    code = memory_consolidate._cmd_config(_args(root))
    assert code == 0
    out = capsys.readouterr().out
    assert "MEMORY_SHORT_PROMOTE_HITS = 5" in out
    assert "varsayılan" not in out.split("MEMORY_SHORT_PROMOTE_HITS = 5")[1].split("\n")[0]
    assert "MEMORY_CONSOLIDATION_INTERVAL_HOURS = 24 (varsayılan)" in out


def test_config_write_updates_env_file_and_preserves_other_lines(tmp_path):
    root = make_root(tmp_path)
    env_path = root / "backend" / ".env"
    env_path.write_text("AUTH_TOKEN=x\nPORT=8000\n", encoding="utf-8")
    code = memory_consolidate._cmd_config(
        _args(root, auto_delete="off", short_promote_hits=5)
    )
    assert code == 0
    content = env_path.read_text(encoding="utf-8")
    assert "MEMORY_AUTO_DELETE_ENABLED=false" in content
    assert "MEMORY_SHORT_PROMOTE_HITS=5" in content
    assert "AUTH_TOKEN=x" in content
    assert "PORT=8000" in content


def test_config_write_json_mode_reports_updated_keys(tmp_path, capsys):
    root = make_root(tmp_path)
    (root / "backend" / ".env").write_text("AUTH_TOKEN=x\n", encoding="utf-8")
    code = memory_consolidate._cmd_config(
        _args(root, json=True, auto_delete="off", short_promote_hits=5)
    )
    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload == {
        "ok": True,
        "updated": {"MEMORY_AUTO_DELETE_ENABLED": "false", "MEMORY_SHORT_PROMOTE_HITS": "5"},
    }


def test_config_below_minimum_rejected_without_writing(tmp_path, capsys):
    root = make_root(tmp_path)
    env_path = root / "backend" / ".env"
    env_path.write_text("AUTH_TOKEN=x\n", encoding="utf-8")
    code = memory_consolidate._cmd_config(_args(root, short_promote_hits=0))
    assert code == 1
    assert "en az" in capsys.readouterr().err
    assert "MEMORY_SHORT_PROMOTE_HITS" not in env_path.read_text(encoding="utf-8")


def test_config_works_without_a_running_backend(tmp_path):
    # No fake_api fixture used here at all -- config must not need the
    # backend to be reachable.
    root = make_root(tmp_path)
    (root / "backend" / ".env").write_text("AUTH_TOKEN=x\n", encoding="utf-8")
    code = memory_consolidate._cmd_config(_args(root, interval_hours=48))
    assert code == 0
    assert "MEMORY_CONSOLIDATION_INTERVAL_HOURS=48" in (root / "backend" / ".env").read_text(
        encoding="utf-8"
    )
