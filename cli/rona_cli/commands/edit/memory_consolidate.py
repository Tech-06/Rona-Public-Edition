"""`rona edit memory consolidate run|status|config` -- the memory
consolidation engine's CLI surface.

`run`/`status` talk to a running backend (`/api/memory/consolidation*`),
same as the rest of `memory.py`. `config` is different on purpose: it
reads/writes `backend/.env` directly (like `rona edit model`/`lang`) and
works without a running backend at all -- so settings can be inspected or
changed before the backend has ever been started.
"""

from __future__ import annotations

import argparse
import json as jsonlib

from rona_cli import envio, http, i18n, ui
from rona_cli.backend_client import BackendUnavailable, backend_client
from rona_cli.paths import RonaNotFoundError, RonaPaths, find_root

# Mirrors backend/app/config.py's Settings memory_* fields one-to-one:
# (flag, dest, env key, kind ("int"/"onoff"), minimum (int kind only),
# default). Keep this in sync if those defaults ever change.
_CONFIG_SPECS = (
    ("--interval-hours", "interval_hours", "MEMORY_CONSOLIDATION_INTERVAL_HOURS", "int", 0, 24),
    ("--auto-promote", "auto_promote", "MEMORY_AUTO_PROMOTE_ENABLED", "onoff", None, True),
    ("--auto-archive", "auto_archive", "MEMORY_AUTO_ARCHIVE_ENABLED", "onoff", None, True),
    ("--auto-delete", "auto_delete", "MEMORY_AUTO_DELETE_ENABLED", "onoff", None, True),
    ("--short-promote-hits", "short_promote_hits", "MEMORY_SHORT_PROMOTE_HITS", "int", 1, 3),
    (
        "--seasonal-promote-hits",
        "seasonal_promote_hits",
        "MEMORY_SEASONAL_PROMOTE_HITS",
        "int",
        1,
        10,
    ),
    (
        "--seasonal-archive-days",
        "seasonal_archive_days",
        "MEMORY_SEASONAL_ARCHIVE_DAYS",
        "int",
        1,
        90,
    ),
    ("--short-delete-days", "short_delete_days", "MEMORY_SHORT_DELETE_DAYS", "int", 1, 7),
    (
        "--short-delete-below-hits",
        "short_delete_below_hits",
        "MEMORY_SHORT_DELETE_BELOW_HITS",
        "int",
        1,
        3,
    ),
    ("--access-top-n", "access_top_n", "MEMORY_ACCESS_TOP_N", "int", 1, 3),
    (
        "--access-cooldown-hours",
        "access_cooldown_hours",
        "MEMORY_ACCESS_COOLDOWN_HOURS",
        "int",
        0,
        12,
    ),
)


def _resolve_client(args: argparse.Namespace) -> tuple[http.Client | None, str | None]:
    try:
        paths = RonaPaths(find_root(args.root))
        return backend_client(paths), None
    except (RonaNotFoundError, BackendUnavailable) as exc:
        return None, str(exc)


def _resolve_paths(args: argparse.Namespace) -> RonaPaths | None:
    try:
        return RonaPaths(find_root(args.root))
    except RonaNotFoundError as exc:
        _emit_error(args, str(exc))
        return None


def _emit_error(args: argparse.Namespace, message: str) -> None:
    if args.json:
        print(jsonlib.dumps({"ok": False, "error": message}, ensure_ascii=False))
    else:
        ui.error(message)


def _format_policy_value(value: object) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def _default_display(kind: str, default: object) -> str:
    if kind == "onoff":
        return "true" if default else "false"
    return str(default)


def _cmd_run(args: argparse.Namespace) -> int:
    client, error = _resolve_client(args)
    if client is None:
        _emit_error(args, error)
        return 1
    try:
        result = client.post(
            "/api/memory/consolidation/run", {"dry_run": args.dry_run}, timeout=60
        )
    except http.ApiError as exc:
        _emit_error(args, str(exc))
        return 1
    if args.json:
        print(jsonlib.dumps(result, ensure_ascii=False))
        return 0

    if args.dry_run:
        ui.heading(i18n.t("memory.consolidate_preview_heading"))
    else:
        ui.heading(i18n.t("memory.consolidate_done_heading", run_id=result.get("run_id")))

    counts = result.get("counts", {})
    ui.info(
        i18n.t(
            "memory.consolidate_counts_line",
            promoted_short=counts.get("promoted_short", 0),
            promoted_seasonal=counts.get("promoted_seasonal", 0),
            archived=counts.get("archived", 0),
            deleted=counts.get("deleted", 0),
        )
    )

    any_items = False
    for item in result.get("promoted_short", []):
        any_items = True
        ui.info(
            i18n.t(
                "memory.consolidate_item_promoted_short",
                id=item["id"],
                hits=item["hits"],
                preview=item["preview"],
            )
        )
    for item in result.get("promoted_seasonal", []):
        any_items = True
        ui.info(
            i18n.t(
                "memory.consolidate_item_promoted_seasonal",
                id=item["id"],
                hits=item["hits"],
                preview=item["preview"],
            )
        )
    for item in result.get("archived", []):
        any_items = True
        ui.info(
            i18n.t(
                "memory.consolidate_item_archived",
                id=item["id"],
                layer=item["layer"],
                preview=item["preview"],
            )
        )
    for item in result.get("deleted", []):
        any_items = True
        ui.info(
            i18n.t(
                "memory.consolidate_item_deleted",
                id=item["id"],
                hits=item["hits"],
                preview=item["preview"],
            )
        )
    if not any_items:
        ui.info(i18n.t("memory.consolidate_nothing"))
    return 0


def _cmd_status(args: argparse.Namespace) -> int:
    client, error = _resolve_client(args)
    if client is None:
        _emit_error(args, error)
        return 1
    try:
        result = client.get("/api/memory/consolidation")
    except http.ApiError as exc:
        _emit_error(args, str(exc))
        return 1
    if args.json:
        print(jsonlib.dumps(result, ensure_ascii=False))
        return 0

    scheduler = result.get("scheduler") or {}
    if scheduler.get("active"):
        ui.info(
            i18n.t(
                "memory.consolidate_status_scheduler_active",
                interval=scheduler.get("interval_hours"),
                next_run=scheduler.get("next_run_at") or i18n.t("memory.never"),
            )
        )
    else:
        ui.info(i18n.t("memory.consolidate_status_scheduler_inactive"))
    if result.get("running"):
        ui.info(i18n.t("memory.consolidate_status_running"))

    ui.info(i18n.t("memory.consolidate_status_policy_heading"))
    policy = result.get("policy") or {}
    for _flag, _dest, env_key, _kind, _minimum, _default in _CONFIG_SPECS:
        # The backend reports its policy by Settings field name minus the
        # "memory_" prefix (e.g. auto_delete_enabled), which is the env key
        # lowercased -- not this CLI's shorter flag dest (auto_delete).
        policy_key = env_key.lower().removeprefix("memory_")
        if policy_key in policy:
            ui.info(f"{env_key} = {_format_policy_value(policy[policy_key])}")

    runs = (result.get("runs") or [])[:5]
    if runs:
        ui.info(i18n.t("memory.consolidate_status_runs_heading"))
        for run in runs:
            line = i18n.t(
                "memory.consolidate_status_run_line",
                id=run["id"],
                triggered_by=run["triggered_by"],
                finished_at=run["finished_at"],
                promoted_short=run["promoted_short"],
                promoted_seasonal=run["promoted_seasonal"],
                archived=run["archived"],
                deleted=run["deleted"],
            )
            if run.get("error"):
                line += " " + i18n.t("memory.consolidate_status_run_error", error=run["error"])
            ui.info(line)
    else:
        ui.info(i18n.t("memory.consolidate_status_no_runs"))
    return 0


def _cmd_config(args: argparse.Namespace) -> int:
    paths = _resolve_paths(args)
    if paths is None:
        return 1

    given: dict[str, str] = {}
    for flag, dest, env_key, kind, minimum, _default in _CONFIG_SPECS:
        value = getattr(args, dest)
        if value is None:
            continue
        if kind == "int":
            if value < minimum:
                _emit_error(
                    args, i18n.t("memory.config_below_minimum", flag=flag, minimum=minimum)
                )
                return 1
            given[env_key] = str(value)
        else:
            given[env_key] = "true" if value == "on" else "false"

    if given:
        envio.write_env_updates(paths.backend_env, given)
        if args.json:
            print(jsonlib.dumps({"ok": True, "updated": given}, ensure_ascii=False))
        else:
            ui.ok(i18n.t("memory.config_saved"))
        return 0

    env = envio.read_env_file(paths.backend_env)
    values: dict[str, str] = {}
    is_default: dict[str, bool] = {}
    for _flag, _dest, env_key, kind, _minimum, default in _CONFIG_SPECS:
        if env_key in env:
            values[env_key] = env[env_key]
            is_default[env_key] = False
        else:
            values[env_key] = _default_display(kind, default)
            is_default[env_key] = True

    if args.json:
        print(jsonlib.dumps({"ok": True, "values": values}, ensure_ascii=False))
        return 0

    marker = i18n.t("memory.config_default_marker")
    for _flag, _dest, env_key, _kind, _minimum, _default in _CONFIG_SPECS:
        suffix = f" ({marker})" if is_default[env_key] else ""
        ui.info(f"{env_key} = {values[env_key]}{suffix}")
    return 0


def register(sub, common) -> None:
    parser = sub.add_parser(
        "consolidate", parents=[common], help=i18n.t("memory.help_consolidate_group")
    )
    consolidate_sub = parser.add_subparsers(dest="consolidate_command", required=True)

    p_run = consolidate_sub.add_parser(
        "run", parents=[common], help=i18n.t("memory.help_consolidate_run")
    )
    p_run.add_argument(
        "--dry-run", dest="dry_run", action="store_true", help=i18n.t("memory.help_dry_run_flag")
    )
    p_run.set_defaults(func=_cmd_run)

    p_status = consolidate_sub.add_parser(
        "status", parents=[common], help=i18n.t("memory.help_consolidate_status")
    )
    p_status.set_defaults(func=_cmd_status)

    p_config = consolidate_sub.add_parser(
        "config", parents=[common], help=i18n.t("memory.help_consolidate_config")
    )
    for flag, dest, _env_key, kind, _minimum, _default in _CONFIG_SPECS:
        help_key = f"memory.help_config_{dest}"
        if kind == "onoff":
            p_config.add_argument(
                flag, dest=dest, choices=("on", "off"), default=None, help=i18n.t(help_key)
            )
        else:
            p_config.add_argument(flag, dest=dest, type=int, default=None, help=i18n.t(help_key))
    p_config.set_defaults(func=_cmd_config)
