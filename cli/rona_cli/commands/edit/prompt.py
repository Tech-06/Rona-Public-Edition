"""`rona edit prompt list|show|edit|reset` -- a thin CLI over the backend's
`/api/prompts*` endpoints (see app/prompts_api.py). Like `rona edit memory`,
this needs a running, reachable backend; unlike it, `edit` also needs a
text editor (or `--file`) since prompts are multi-line Markdown.

Follows `edit/memory.py`'s conventions: `_resolve_client`/`_emit_error`,
`--json` passthrough, `ui.confirm` for destructive actions without `--yes`.

`edit`'s draft-file handling:
- Without `--file`, the current content is written to a temp file
  (`rona-prompt-<id>-*.md`, UTF-8, `\n` line endings only) and the user's
  editor opens it and blocks (`env._editor_command(wait=True)`) until
  closed.
- The file is read back (`utf-8-sig` strips a possible BOM; `\r\n` is
  normalized to `\n`) and compared to the original content.
- No change -> the temp file is deleted and nothing is sent.
- Changed -> `PUT` with `base_version` from the `GET` above. On *any*
  failure (409 stale version, 422 validation, or anything else) the draft
  file is deliberately left on disk and its path is printed -- losing the
  user's edits because a save failed would be worse than leaving a stray
  temp file around.
- On success the temp file is deleted.
`--file PATH` skips the temp file/editor dance entirely: PATH is read as
the new content and PATH itself is left alone either way (it's the user's
own file, not ours to delete).
"""

from __future__ import annotations

import argparse
import json as jsonlib
import os
import subprocess
import tempfile
from pathlib import Path

from rona_cli import http, i18n, ui
from rona_cli.backend_client import BackendUnavailable, backend_client
from rona_cli.commands.edit import env
from rona_cli.paths import RonaNotFoundError, RonaPaths, find_root


def _resolve_client(args: argparse.Namespace) -> tuple[http.Client | None, str | None]:
    try:
        paths = RonaPaths(find_root(args.root))
        return backend_client(paths), None
    except (RonaNotFoundError, BackendUnavailable) as exc:
        return None, str(exc)


def _emit_error(args: argparse.Namespace, message: str) -> None:
    if args.json:
        print(jsonlib.dumps({"ok": False, "error": message}, ensure_ascii=False))
    else:
        ui.error(message)


def _write_temp_prompt(prompt_id: str, content: str) -> Path:
    fd, raw_path = tempfile.mkstemp(prefix=f"rona-prompt-{prompt_id}-", suffix=".md")
    os.close(fd)
    path = Path(raw_path)
    path.write_text(content, encoding="utf-8", newline="\n")
    return path


def _read_prompt_file(path: Path) -> str:
    # "utf-8-sig" strips a leading BOM if present, and decodes exactly like
    # plain utf-8 otherwise -- either way the caller gets clean text.
    text = path.read_text(encoding="utf-8-sig")
    return text.replace("\r\n", "\n")


def _cmd_list(args: argparse.Namespace) -> int:
    client, error = _resolve_client(args)
    if client is None:
        _emit_error(args, error)
        return 1
    try:
        result = client.get("/api/prompts")
    except http.ApiError as exc:
        _emit_error(args, str(exc))
        return 1
    if args.json:
        print(jsonlib.dumps(result, ensure_ascii=False))
        return 0
    prompts = result.get("prompts", [])
    if not prompts:
        ui.info(i18n.t("prompt.list_empty"))
        return 0
    for item in prompts:
        markers = []
        if item.get("customized"):
            markers.append(i18n.t("prompt.customized_marker"))
        if item.get("default_changed"):
            markers.append(i18n.t("prompt.default_changed_marker"))
        suffix = f"  {' '.join(markers)}" if markers else ""
        ui.info(f"{item['id']:<16} {item['group']:<10}{suffix}")
    return 0


def _cmd_show(args: argparse.Namespace) -> int:
    client, error = _resolve_client(args)
    if client is None:
        _emit_error(args, error)
        return 1
    try:
        result = client.get(f"/api/prompts/{args.id}")
    except http.ApiError as exc:
        _emit_error(args, str(exc))
        return 1
    if args.json:
        print(jsonlib.dumps(result, ensure_ascii=False))
        return 0
    key = "default_content" if args.default else "content"
    print(result.get(key, ""))
    return 0


def _emit_save_failure(args: argparse.Namespace, exc: http.ApiError, draft_path: Path) -> None:
    message = i18n.t("prompt.conflict") if exc.status == 409 else str(exc)
    if args.json:
        print(
            jsonlib.dumps(
                {"ok": False, "error": message, "kept_draft": str(draft_path)},
                ensure_ascii=False,
            )
        )
    else:
        ui.error(message)
        ui.info(i18n.t("prompt.kept_draft", path=draft_path))


def _cmd_edit(args: argparse.Namespace) -> int:
    client, error = _resolve_client(args)
    if client is None:
        _emit_error(args, error)
        return 1
    try:
        current = client.get(f"/api/prompts/{args.id}")
    except http.ApiError as exc:
        _emit_error(args, str(exc))
        return 1

    original_content = current["content"]
    base_version = current["version"]

    is_temp = not args.file
    if args.file:
        draft_path = Path(args.file)
        try:
            new_content = _read_prompt_file(draft_path)
        except OSError as exc:
            _emit_error(args, str(exc))
            return 1
    else:
        draft_path = _write_temp_prompt(args.id, original_content)
        command = [*env._editor_command(wait=True), str(draft_path)]
        try:
            subprocess.run(command, check=False)
        except FileNotFoundError:
            _emit_error(args, i18n.t("env.editor_failed", command=" ".join(command)))
            ui.info(i18n.t("env.open_manually", path=draft_path))
            return 1
        try:
            new_content = _read_prompt_file(draft_path)
        except OSError as exc:
            _emit_error(args, str(exc))
            return 1

    if new_content == original_content.replace("\r\n", "\n"):
        if is_temp:
            draft_path.unlink(missing_ok=True)
        if args.json:
            print(jsonlib.dumps({"ok": True, "changed": False}, ensure_ascii=False))
        else:
            ui.info(i18n.t("prompt.no_changes"))
        return 0

    try:
        result = client.put(
            f"/api/prompts/{args.id}", {"content": new_content, "base_version": base_version}
        )
    except http.ApiError as exc:
        # Keep the draft on ANY failure, not just 409/422 -- if the save
        # didn't provably succeed, deleting the user's edits would be worse
        # than leaving a stray temp file behind.
        _emit_save_failure(args, exc, draft_path)
        return 1

    if is_temp:
        draft_path.unlink(missing_ok=True)
    if args.json:
        print(jsonlib.dumps(result, ensure_ascii=False))
    else:
        ui.ok(i18n.t("prompt.saved"))
        for warning in result.get("warnings", []) or []:
            ui.warn(warning)
    return 0


def _cmd_reset(args: argparse.Namespace) -> int:
    if not args.yes and not args.json:
        confirmed = ui.confirm(i18n.t("prompt.confirm_reset", id=args.id), default=False)
        if not confirmed:
            ui.info(i18n.t("common.cancelled"))
            return 1

    client, error = _resolve_client(args)
    if client is None:
        _emit_error(args, error)
        return 1
    try:
        result = client.delete(f"/api/prompts/{args.id}")
    except http.ApiError as exc:
        _emit_error(args, str(exc))
        return 1
    if args.json:
        print(jsonlib.dumps(result, ensure_ascii=False))
    else:
        ui.ok(i18n.t("prompt.reset_done", id=args.id))
    return 0


def register(subparsers, common) -> None:
    parser = subparsers.add_parser("prompt", parents=[common], help=i18n.t("prompt.help_group"))
    sub = parser.add_subparsers(dest="prompt_command", required=True)

    p_list = sub.add_parser("list", parents=[common], help=i18n.t("prompt.help_list"))
    p_list.set_defaults(func=_cmd_list)

    p_show = sub.add_parser("show", parents=[common], help=i18n.t("prompt.help_show"))
    p_show.add_argument("id")
    p_show.add_argument("--default", action="store_true", help=i18n.t("prompt.help_default_flag"))
    p_show.set_defaults(func=_cmd_show)

    p_edit = sub.add_parser("edit", parents=[common], help=i18n.t("prompt.help_edit"))
    p_edit.add_argument("id")
    p_edit.add_argument("--file", default=None, help=i18n.t("prompt.help_file_flag"))
    p_edit.set_defaults(func=_cmd_edit)

    p_reset = sub.add_parser("reset", parents=[common], help=i18n.t("prompt.help_reset"))
    p_reset.add_argument("id")
    p_reset.add_argument("--yes", action="store_true", help=i18n.t("common.help_skip_confirm"))
    p_reset.set_defaults(func=_cmd_reset)
