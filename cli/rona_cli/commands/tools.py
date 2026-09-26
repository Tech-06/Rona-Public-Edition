"""`rona tools list|available|install|update|uninstall|verify|config|actions|run`
-- a thin CLI over the backend's toolbox.manager, delegating to its own venv
python the same way `rona web` delegates to web-client's own `python -m
webui` (see commands/web.py). Deliberately NOT importing anything from
toolbox/ itself -- this package is stdlib-only and keeps working
without the backend ever being installed; everything here just shells
out to `python -m toolbox.manager ...` with cwd=backend/.

Two run modes:
- install/update/uninstall/run, and `config --edit`, inherit stdio: a
  package's own config prompts (getpass for secrets), the health-check
  retry/keep/cancel choice, the dependency confirmation and an action's
  input_required round trips all need a live terminal, so their output is
  never captured or re-rendered.
- list/available/verify/actions, and `config` without --edit, instead run
  the manager with --json, captured, and re-print the parsed result
  through this CLI's own (localized) table -- these never need
  interactivity. If `rona` itself was given --json, the manager's own JSON
  payload is passed through unchanged.

manager.py's own text (interactive prompts, its help output) stays
English -- toolbox/ is deliberately out of scope for LANGUAGE (see the
backend's i18n.py docstring); only the wrapping this module itself
prints goes through rona_cli.i18n.
"""

from __future__ import annotations

import argparse
import json as jsonlib
import subprocess

from rona_cli import i18n, ui
from rona_cli.paths import RonaNotFoundError, RonaPaths, find_root


def _resolve(args: argparse.Namespace) -> RonaPaths | None:
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


def _run_captured(paths: RonaPaths, args: argparse.Namespace, *manager_args: str) -> dict | None:
    try:
        python = paths.backend_python()
    except RonaNotFoundError as exc:
        _emit_error(args, str(exc))
        return None
    cmd = [str(python), "-m", "toolbox.manager", "--json", *manager_args]
    result = subprocess.run(cmd, cwd=paths.backend_dir, capture_output=True, text=True, check=False)
    lines = result.stdout.strip().splitlines()
    try:
        payload = jsonlib.loads(lines[-1]) if lines else None
    except jsonlib.JSONDecodeError:
        payload = None
    if payload is None:
        _emit_error(args, result.stderr.strip() or i18n.t("tools.manager_no_output"))
        return None
    return payload


def _run_inherited(
    paths: RonaPaths,
    args: argparse.Namespace,
    *manager_args: str,
    forward_json: bool = False,
) -> int:
    try:
        python = paths.backend_python()
    except RonaNotFoundError as exc:
        _emit_error(args, str(exc))
        return 1
    cmd = [str(python), "-m", "toolbox.manager"]
    if forward_json and args.json:
        # These commands print a final result the caller may want to parse,
        # but still need a live terminal on the way there -- so the manager
        # emits the JSON itself rather than us capturing and re-printing it.
        cmd.append("--json")
    cmd.extend(manager_args)
    result = subprocess.run(cmd, cwd=paths.backend_dir, check=False)
    return result.returncode


def _cmd_list(args: argparse.Namespace) -> int:
    paths = _resolve(args)
    if paths is None:
        return 1
    payload = _run_captured(paths, args, "installed")
    if payload is None:
        return 1
    if args.json:
        print(jsonlib.dumps(payload, ensure_ascii=False))
        return 0 if payload.get("ok") else 1
    if not payload.get("ok"):
        ui.error(payload.get("error", ""))
        return 1
    packages = payload.get("packages", [])
    if not packages:
        ui.info(i18n.t("tools.none_installed"))
        return 0
    for pkg in packages:
        ui.info(f"{pkg['id']}  {pkg['version']}  {pkg['name']}")
    return 0


def _cmd_available(args: argparse.Namespace) -> int:
    paths = _resolve(args)
    if paths is None:
        return 1
    manager_args = ["available"]
    if args.source:
        manager_args.extend(["--source", args.source])
    payload = _run_captured(paths, args, *manager_args)
    if payload is None:
        return 1
    if args.json:
        print(jsonlib.dumps(payload, ensure_ascii=False))
        return 0 if payload.get("ok") else 1
    if not payload.get("ok"):
        ui.error(payload.get("error", ""))
        return 1
    packages = payload.get("packages", [])
    if not packages:
        ui.info(i18n.t("tools.catalog_empty"))
        return 0
    any_update_available = False
    for pkg in packages:
        if pkg.get("installed") and pkg.get("update_available"):
            any_update_available = True
            marker = (
                f" [{i18n.t('tools.update_marker', installed=pkg.get('installed_version'), version=pkg['version'])}]"
            )
        elif pkg.get("installed"):
            marker = f" [{i18n.t('tools.installed_marker')}]"
        else:
            marker = ""
        ui.info(
            f"{pkg['id']}  {pkg['version']}  {pkg['name']}{marker} — {pkg['description']}"
        )
        # None means the catalog doesn't publish dependencies at all, which is
        # not the same as having none -- say nothing rather than imply none.
        requires = pkg.get("requires")
        if requires:
            ui.info("    " + i18n.t("tools.requires", packages=", ".join(requires)))
    if any_update_available:
        ui.info(i18n.t("tools.update_hint"))
    return 0


def _cmd_verify(args: argparse.Namespace) -> int:
    paths = _resolve(args)
    if paths is None:
        return 1
    payload = _run_captured(paths, args, "verify", args.package_id)
    if payload is None:
        return 1
    if args.json:
        print(jsonlib.dumps(payload, ensure_ascii=False))
        return 0 if payload.get("ok") else 1
    if payload.get("ok"):
        ui.ok(payload.get("detail", ""))
        return 0
    ui.error(payload.get("detail", ""))
    return 1


def _cmd_install(args: argparse.Namespace) -> int:
    paths = _resolve(args)
    if paths is None:
        return 1
    manager_args = ["install", args.package_id]
    if args.source:
        manager_args.extend(["--source", args.source])
    for item in args.set or []:
        manager_args.extend(["--set", item])
    if args.yes:
        manager_args.append("--yes")
    if args.keep_on_health_failure:
        manager_args.append("--keep-on-health-failure")
    if args.defer_config:
        manager_args.append("--defer-config")
    return _run_inherited(paths, args, *manager_args)


def _cmd_update(args: argparse.Namespace) -> int:
    paths = _resolve(args)
    if paths is None:
        return 1
    manager_args = ["update", args.package_id]
    if args.source:
        manager_args.extend(["--source", args.source])
    for item in args.set or []:
        manager_args.extend(["--set", item])
    if args.yes:
        manager_args.append("--yes")
    if args.keep_on_health_failure:
        manager_args.append("--keep-on-health-failure")
    if args.defer_config:
        manager_args.append("--defer-config")
    return _run_inherited(paths, args, *manager_args)


def _cmd_uninstall(args: argparse.Namespace) -> int:
    paths = _resolve(args)
    if paths is None:
        return 1
    manager_args = ["uninstall", args.package_id]
    if args.force:
        manager_args.append("--force")
    if args.purge:
        manager_args.append("--purge")
    return _run_inherited(paths, args, *manager_args)


def _cmd_config(args: argparse.Namespace) -> int:
    paths = _resolve(args)
    if paths is None:
        return 1
    manager_args = ["config", args.package_id]
    for item in args.set or []:
        manager_args.extend(["--set", item])
    if args.edit:
        # --edit walks every field on the terminal, masking secrets, so it
        # cannot be captured.
        manager_args.append("--edit")
        return _run_inherited(paths, args, *manager_args, forward_json=True)

    payload = _run_captured(paths, args, *manager_args)
    if payload is None:
        return 1
    if args.json:
        print(jsonlib.dumps(payload, ensure_ascii=False))
        return 0 if payload.get("ok") else 1
    if not payload.get("ok"):
        ui.error(payload.get("error", ""))
        return 1

    if args.set:
        ui.ok(
            i18n.t(
                "tools.config_changed",
                package=payload.get("package", args.package_id),
                fields=", ".join(payload.get("changed", [])),
            )
        )
        detail = payload.get("detail", "")
        if payload.get("health_ok"):
            ui.ok(detail)
        else:
            ui.error(detail)
        ui.info(i18n.t("tools.restart_hint"))
        return 0

    fields = payload.get("fields", [])
    if not fields:
        ui.info(i18n.t("tools.config_none", package=args.package_id))
        return 0
    for field in fields:
        if field.get("secret") and field.get("set"):
            shown = i18n.t("tools.config_secret_set")
        elif field.get("value") in (None, "", []):
            shown = i18n.t("tools.config_not_set")
        else:
            value = field["value"]
            shown = ", ".join(str(v) for v in value) if isinstance(value, list) else str(value)
        ui.info(f"{field['key']}: {shown}")
        if field.get("description"):
            ui.info(f"    {field['description']}")
    return 0


def _cmd_actions(args: argparse.Namespace) -> int:
    paths = _resolve(args)
    if paths is None:
        return 1
    payload = _run_captured(paths, args, "actions", args.package_id)
    if payload is None:
        return 1
    if args.json:
        print(jsonlib.dumps(payload, ensure_ascii=False))
        return 0 if payload.get("ok") else 1
    if not payload.get("ok"):
        ui.error(payload.get("error", ""))
        return 1
    actions = payload.get("actions", [])
    if not actions:
        ui.info(i18n.t("tools.actions_none", package=args.package_id))
        return 0
    for action in actions:
        flags = []
        if action.get("destructive"):
            flags.append(i18n.t("tools.action_destructive"))
        if action.get("cli_only"):
            flags.append(i18n.t("tools.action_cli_only"))
        suffix = f"  [{', '.join(flags)}]" if flags else ""
        ui.info(f"{action['id']}  {action.get('label', '')}{suffix}")
        if action.get("description"):
            ui.info(f"    {action['description']}")
        params = [p["key"] for p in action.get("params", [])]
        if params:
            ui.info("    " + i18n.t("tools.action_params", params=", ".join(params)))
    ui.info(i18n.t("tools.run_hint", package=args.package_id))
    return 0


def _cmd_run(args: argparse.Namespace) -> int:
    paths = _resolve(args)
    if paths is None:
        return 1
    manager_args = ["run", args.package_id, args.action_id]
    for item in args.set or []:
        manager_args.extend(["--set", item])
    if args.yes:
        manager_args.append("--yes")
    # Always inherited: an action that answers input_required needs to ask
    # right here, and the link it prints has to reach the user unmangled.
    return _run_inherited(paths, args, *manager_args, forward_json=True)


def register(subparsers, common) -> None:
    parser = subparsers.add_parser("tools", parents=[common], help=i18n.t("tools.help_group"))
    sub = parser.add_subparsers(dest="tools_command", required=True)

    p_list = sub.add_parser("list", parents=[common], help=i18n.t("tools.help_list"))
    p_list.set_defaults(func=_cmd_list)

    p_available = sub.add_parser("available", parents=[common], help=i18n.t("tools.help_available"))
    p_available.add_argument("--source", default=None, help=i18n.t("tools.help_source_flag"))
    p_available.set_defaults(func=_cmd_available)

    p_install = sub.add_parser("install", parents=[common], help=i18n.t("tools.help_install"))
    p_install.add_argument("package_id")
    p_install.add_argument("--source", default=None, help=i18n.t("tools.help_source_flag"))
    p_install.add_argument(
        "--set", action="append", metavar="[pkg.]key=value", help=i18n.t("tools.help_set_flag")
    )
    p_install.add_argument("--yes", action="store_true", help=i18n.t("common.help_skip_confirm"))
    p_install.add_argument(
        "--keep-on-health-failure", action="store_true", help=i18n.t("tools.help_keep_flag")
    )
    p_install.add_argument(
        "--defer-config", action="store_true", help=i18n.t("tools.help_defer_config_flag")
    )
    p_install.set_defaults(func=_cmd_install)

    p_update = sub.add_parser("update", parents=[common], help=i18n.t("tools.help_update"))
    p_update.add_argument("package_id")
    p_update.add_argument("--source", default=None, help=i18n.t("tools.help_source_flag"))
    p_update.add_argument(
        "--set", action="append", metavar="[pkg.]key=value", help=i18n.t("tools.help_set_flag")
    )
    p_update.add_argument("--yes", action="store_true", help=i18n.t("common.help_skip_confirm"))
    p_update.add_argument(
        "--keep-on-health-failure", action="store_true", help=i18n.t("tools.help_keep_flag")
    )
    p_update.add_argument(
        "--defer-config", action="store_true", help=i18n.t("tools.help_defer_config_flag")
    )
    p_update.set_defaults(func=_cmd_update)

    p_uninstall = sub.add_parser("uninstall", parents=[common], help=i18n.t("tools.help_uninstall"))
    p_uninstall.add_argument("package_id")
    p_uninstall.add_argument("--force", action="store_true", help=i18n.t("tools.help_force_flag"))
    p_uninstall.add_argument(
        "--purge", action="store_true", help=i18n.t("tools.help_purge_flag")
    )
    p_uninstall.set_defaults(func=_cmd_uninstall)

    p_verify = sub.add_parser("verify", parents=[common], help=i18n.t("tools.help_verify"))
    p_verify.add_argument("package_id")
    p_verify.set_defaults(func=_cmd_verify)

    p_config = sub.add_parser("config", parents=[common], help=i18n.t("tools.help_config"))
    p_config.add_argument("package_id")
    p_config.add_argument(
        "--set", action="append", metavar="key=value", help=i18n.t("tools.help_config_set")
    )
    p_config.add_argument("--edit", action="store_true", help=i18n.t("tools.help_config_edit"))
    p_config.set_defaults(func=_cmd_config)

    p_actions = sub.add_parser("actions", parents=[common], help=i18n.t("tools.help_actions"))
    p_actions.add_argument("package_id")
    p_actions.set_defaults(func=_cmd_actions)

    p_run = sub.add_parser("run", parents=[common], help=i18n.t("tools.help_run"))
    p_run.add_argument("package_id")
    p_run.add_argument("action_id")
    p_run.add_argument(
        "--set", action="append", metavar="key=value", help=i18n.t("tools.help_run_set")
    )
    p_run.add_argument("--yes", action="store_true", help=i18n.t("common.help_skip_confirm"))
    p_run.set_defaults(func=_cmd_run)
