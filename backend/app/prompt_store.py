"""Editable prompt storage: default prompt files under ``backend/prompts/``
can each be overridden by a same-named file under ``backend/prompts/custom/``
(git-ignored -- see the root ``.gitignore``), so a `git pull` never
conflicts with, or silently reverts, a customization made from the
dashboard's Prompts panel or ``rona edit prompt``.

Nine prompt ids exist, matching ``backend/prompts/*.md`` one-to-one:
seven "main" prompts assembled every chat turn (see ``app/prompts.py``),
plus the two worker prompts used by background tasks
(``subagents/runner.py``, ``trigger/executor.py``). Everything here reads
from disk on every call -- no caching -- so an edit takes effect on the
very next message/run without a backend restart.

``version`` (used for optimistic-concurrency writes, see :func:`write`) is
always the first 16 hex characters of the sha256 of the *effective* raw
content -- the override's bytes if one exists, else the default file's.
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

import i18n

PROMPTS_DIR = Path(__file__).resolve().parent.parent / "prompts"
CUSTOM_DIR = PROMPTS_DIR / "custom"
META_FILENAME = ".meta.json"
MAX_PROMPT_BYTES = 65536


@dataclass(frozen=True)
class PromptSpec:
    id: str
    filename: str
    group: str
    required_placeholders: tuple[str, ...] = ()
    required_nonempty: bool = False
    contract_markers: tuple[str, ...] = ()


PROMPT_SPECS: tuple[PromptSpec, ...] = (
    PromptSpec(
        "persona",
        "persona.md",
        "main",
        required_placeholders=("PRIMARY_LANGUAGE_RULE",),
    ),
    PromptSpec("output_text", "output_text.md", "main"),
    PromptSpec("user", "user.md", "main"),
    PromptSpec("toolbox", "toolbox.md", "main"),
    PromptSpec("memory", "memory.md", "main"),
    PromptSpec("subagents", "subagents.md", "main"),
    PromptSpec(
        "trigger",
        "trigger.md",
        "main",
        required_placeholders=("EXAMPLE_GREETING",),
    ),
    PromptSpec(
        "subagent_worker",
        "subagent_worker.md",
        "subagent",
        required_nonempty=True,
    ),
    PromptSpec(
        "trigger_worker",
        "trigger_worker.md",
        "trigger",
        required_nonempty=True,
        contract_markers=("outcome", "condition_not_met"),
    ),
)

_SPECS_BY_ID: dict[str, PromptSpec] = {s.id: s for s in PROMPT_SPECS}
MAIN_PROMPT_IDS: list[str] = [s.id for s in PROMPT_SPECS if s.group == "main"]

# {{...}} placeholders substituted into prompt files at load time, so the
# handful of spots that genuinely depend on LANGUAGE (persona.md's "speak
# X" directive, trigger.md's worked example) don't require a whole second
# copy of every prompt file -- everything else in these files is
# instructions *to the model*, not shown to the user, and is deliberately
# left as plain English prose regardless of LANGUAGE (see the language
# plan's rationale). A prompt spec that requires one of these names
# (see PROMPT_SPECS above) must keep the literal "{{NAME}}" token
# somewhere in its content -- validate() below enforces that on save so a
# customization can never silently drop the language/example behavior.
PLACEHOLDERS: dict[str, Callable[[], str]] = {
    "PRIMARY_LANGUAGE_RULE": lambda: i18n.t("prompt.primary_language_rule"),
    "EXAMPLE_GREETING": lambda: i18n.t("prompt.example_greeting"),
}


def substitute_placeholders(content: str) -> str:
    for name, resolve in PLACEHOLDERS.items():
        content = content.replace("{{" + name + "}}", resolve())
    return content


def placeholder_values() -> list[dict[str, str]]:
    return [{"name": name, "value": resolve()} for name, resolve in PLACEHOLDERS.items()]


class PromptNotFound(KeyError):
    """Raised for an id outside the fixed nine in PROMPT_SPECS."""


class PromptValidationError(ValueError):
    def __init__(self, messages: list[str]):
        self.messages = messages
        super().__init__("; ".join(messages))


class PromptConflict(Exception):
    """The caller's ``base_version`` no longer matches the stored content."""

    def __init__(self, current_version: str):
        self.current_version = current_version
        super().__init__(f"stale base_version, current is {current_version}")


def spec(prompt_id: str) -> PromptSpec:
    try:
        return _SPECS_BY_ID[prompt_id]
    except KeyError:
        raise PromptNotFound(prompt_id) from None


def default_path(prompt_id: str) -> Path:
    return PROMPTS_DIR / spec(prompt_id).filename


def override_path(prompt_id: str) -> Path:
    return CUSTOM_DIR / spec(prompt_id).filename


def resolve_path(prompt_id: str) -> Path:
    override = override_path(prompt_id)
    return override if override.is_file() else default_path(prompt_id)


def _read_default_text(prompt_id: str) -> str:
    path = default_path(prompt_id)
    if not path.is_file():
        return ""
    return path.read_text(encoding="utf-8")


def load_text(prompt_id: str) -> str:
    """Raw effective content (override if present, else default); "" if
    even the default file is missing from disk."""
    path = resolve_path(prompt_id)
    if not path.is_file():
        return ""
    return path.read_text(encoding="utf-8")


def load_rendered(prompt_id: str) -> str:
    return substitute_placeholders(load_text(prompt_id).strip())


def load_worker_prompt(prompt_id: str) -> str:
    """Used by subagents/runner.py and trigger/executor.py. Deliberately
    not placeholder-substituted -- neither worker prompt uses one -- and
    keeps the exact FileNotFoundError/ValueError shape those two modules
    always raised, so a broken install fails the same way it used to."""
    path = resolve_path(prompt_id)
    if not path.is_file():
        raise FileNotFoundError(f"Worker prompt file not found: {path}")
    content = path.read_text(encoding="utf-8").strip()
    if not content:
        raise ValueError(f"Worker prompt file is empty: {path}")
    return content


def content_version(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def _meta_path() -> Path:
    return CUSTOM_DIR / META_FILENAME


def _read_meta() -> dict[str, Any]:
    path = _meta_path()
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _atomic_write(path: Path, text: str, attempts: int = 5, delay: float = 0.1) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    data = text.encode("utf-8")
    last_exc: OSError | None = None
    for attempt in range(attempts):
        tmp = tempfile.NamedTemporaryFile(
            mode="wb", dir=path.parent, prefix=".tmp-", delete=False
        )
        tmp_path = Path(tmp.name)
        try:
            tmp.write(data)
            tmp.flush()
            os.fsync(tmp.fileno())
            tmp.close()
            os.replace(tmp_path, path)
            return
        except PermissionError as exc:
            tmp.close()
            tmp_path.unlink(missing_ok=True)
            last_exc = exc
            if attempt < attempts - 1:
                time.sleep(delay)
        except OSError:
            tmp.close()
            tmp_path.unlink(missing_ok=True)
            raise
    assert last_exc is not None
    raise last_exc


def _write_meta(meta: dict[str, Any]) -> None:
    _atomic_write(_meta_path(), json.dumps(meta, ensure_ascii=False, indent=2))


_lock = threading.Lock()


def summary(prompt_id: str) -> dict[str, Any]:
    prompt_spec = spec(prompt_id)
    override = override_path(prompt_id)
    customized = override.is_file()
    default_text = _read_default_text(prompt_id)
    default_version = content_version(default_text)
    default_changed: bool | None = None
    updated_at: str | None = None
    if customized:
        raw = override.read_text(encoding="utf-8")
        stat = override.stat()
        updated_at = datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat()
        stored = _read_meta().get(prompt_id)
        stored_default_version = stored.get("default_version") if stored else None
        if stored_default_version is not None:
            default_changed = stored_default_version != default_version
    else:
        raw = default_text
    return {
        "id": prompt_id,
        "filename": prompt_spec.filename,
        "group": prompt_spec.group,
        "customized": customized,
        "default_changed": default_changed,
        "updated_at": updated_at,
        "size_bytes": len(raw.encode("utf-8")),
        "required_placeholders": list(prompt_spec.required_placeholders),
        "required_nonempty": prompt_spec.required_nonempty,
    }


def read(prompt_id: str) -> dict[str, Any]:
    spec(prompt_id)  # raises PromptNotFound early for an unknown id
    override = override_path(prompt_id)
    default_text = _read_default_text(prompt_id)
    raw = override.read_text(encoding="utf-8") if override.is_file() else default_text
    result = summary(prompt_id)
    result.update(
        {
            "content": raw,
            "default_content": default_text,
            "version": content_version(raw),
            "default_version": content_version(default_text),
        }
    )
    return result


def list_prompts() -> list[dict[str, Any]]:
    return [summary(prompt_spec.id) for prompt_spec in PROMPT_SPECS]


def validate(prompt_spec: PromptSpec, content: str) -> list[str]:
    errors: list[str] = []
    size = len(content.encode("utf-8"))
    if size > MAX_PROMPT_BYTES:
        errors.append(i18n.t("prompts.too_large", limit=MAX_PROMPT_BYTES))
    missing_placeholders = [
        name
        for name in prompt_spec.required_placeholders
        if "{{" + name + "}}" not in content
    ]
    if missing_placeholders:
        errors.append(
            i18n.t("prompts.missing_placeholder", names=", ".join(missing_placeholders))
        )
    if prompt_spec.required_nonempty and not content.strip():
        errors.append(i18n.t("prompts.empty"))
    if errors:
        raise PromptValidationError(errors)
    warnings: list[str] = []
    missing_markers = [
        marker for marker in prompt_spec.contract_markers if marker not in content
    ]
    if missing_markers:
        warnings.append(
            i18n.t("prompts.contract_warning", markers=", ".join(missing_markers))
        )
    return warnings


def write(prompt_id: str, content: str, base_version: str) -> dict[str, Any]:
    prompt_spec = spec(prompt_id)
    normalized = content.replace("\r\n", "\n")
    if not normalized.endswith("\n"):
        normalized += "\n"
    with _lock:
        current = read(prompt_id)
        if base_version != current["version"]:
            raise PromptConflict(current["version"])
        warnings = validate(prompt_spec, normalized)
        _atomic_write(override_path(prompt_id), normalized)
        meta = _read_meta()
        meta[prompt_id] = {"default_version": current["default_version"]}
        _write_meta(meta)
    result = read(prompt_id)
    result["warnings"] = warnings
    return result


def reset(prompt_id: str) -> dict[str, Any]:
    spec(prompt_id)
    with _lock:
        override = override_path(prompt_id)
        if override.is_file():
            override.unlink()
        meta = _read_meta()
        if prompt_id in meta:
            del meta[prompt_id]
            _write_meta(meta)
    return read(prompt_id)
