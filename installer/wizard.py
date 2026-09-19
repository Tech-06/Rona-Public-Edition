"""Interactive post-install configuration: Flash (required), Pro
(optional), and the Gemini embedding (optional) model settings.

Runs only in a genuinely interactive session (never with --yes/--json,
which imply non-interactive automation) and only when the backend was
actually part of this run. Each block can be skipped by typing 's' at
any prompt; a skipped Flash leaves the backend unable to start until
`rona edit model flash` fills it in later (this is stated to the user).

Reuses rona_cli.providers (added to sys.path by installer/main.py) for
the real-API-call verification, the exact same code path
`rona edit model --test` uses later -- so "does this key/model work"
means the same thing in both places.
"""

from __future__ import annotations

import getpass
from pathlib import Path
from typing import Any

from rona_cli import envio, providers

from installer import ui

_MODEL_FIELDS = {
    "name": "Model adı",
    "url": "API taban URL'si",
    "key": "API anahtarı",
    "headers": "Ek HTTP başlıkları (JSON, boş = yok)",
}
_MODEL_SECRET_FIELDS = {"key"}

FLASH_ENV_MAP = {
    "name": "FLASH_MODEL",
    "url": "FLASH_MODEL_URL",
    "key": "FLASH_MODEL_API",
    "headers": "FLASH_MODEL_HEADERS",
}
PRO_ENV_MAP = {
    "name": "PRO_MODEL",
    "url": "PRO_MODEL_URL",
    "key": "PRO_MODEL_API",
    "headers": "PRO_MODEL_HEADERS",
}

_EMBEDDING_FIELDS = {"key": "Google API anahtarı", "name": "Embedding model adı"}
_EMBEDDING_SECRET_FIELDS = {"key"}
EMBEDDING_ENV_MAP = {"key": "GOOGLE_API_KEY", "name": "EMBEDDING_MODEL_NAME"}

_SKIP_WORDS = {"s", "skip", "atla"}


def _mask(value: str) -> str:
    if not value:
        return "(boş)"
    if len(value) <= 4:
        return "*" * len(value)
    return f"{'*' * (len(value) - 4)}{value[-4:]}"


def _read_field(prompt: str, *, secret: bool) -> str:
    try:
        return getpass.getpass(prompt) if secret else input(prompt)
    except (EOFError, KeyboardInterrupt):
        print()
        return "s"


def _prompt_fields(
    fields: dict[str, str], secret_fields: set[str], current: dict[str, str]
) -> dict[str, str] | None:
    """Prompts for each field in order; blank keeps the current value.
    Typing 's'/'skip'/'atla' (case-insensitive) on any field abandons the
    whole block and returns None.
    """
    collected: dict[str, str] = {}
    for key, label in fields.items():
        shown = _mask(current.get(key, "")) if key in secret_fields else (current.get(key) or "(boş)")
        raw = _read_field(f"  {label} [{shown}]: ", secret=key in secret_fields).strip()
        if raw.lower() in _SKIP_WORDS:
            return None
        if raw:
            collected[key] = raw
    return collected


def _ask_choice(options: list[str]) -> int:
    """Returns the chosen option's index. Defaults to the last (safest --
    typically "skip") option on EOF/interrupt."""
    while True:
        for index, option in enumerate(options, start=1):
            ui.info(f"  {index}) {option}")
        try:
            raw = input("> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return len(options) - 1
        if raw.isdigit() and 1 <= int(raw) <= len(options):
            return int(raw) - 1
        ui.warn("Geçersiz seçim.")


def _test_chat(candidate: dict[str, str]) -> tuple[bool, str]:
    try:
        headers = providers.parse_headers(candidate.get("headers"))
    except ValueError as exc:
        return False, str(exc)
    return providers.test_chat_model(
        candidate.get("url", ""), candidate.get("key", ""), candidate.get("name", ""), headers
    )


def _test_embedding(candidate: dict[str, str]) -> tuple[bool, str]:
    return providers.test_embedding(candidate.get("key", ""), candidate.get("name", ""))


def _run_block(
    title: str,
    fields: dict[str, str],
    secret_fields: set[str],
    current: dict[str, str],
    *,
    required: bool,
    test_fn,
) -> dict[str, str] | None:
    """Returns the values to save, or None if the block ends up skipped."""
    ui.step(title)
    hint = "gerekli ama" if required else "opsiyonel;"
    ui.info(f"Bu adım {hint} istersen 's' yazarak atlayabilirsin.")

    working_current = dict(current)
    while True:
        collected = _prompt_fields(fields, secret_fields, working_current)
        if collected is None:
            return None
        candidate = {**working_current, **collected}
        if not any(candidate.get(key) for key in fields):
            return None  # nothing entered and nothing pre-existing either

        ok, detail = test_fn(candidate)
        if ok:
            ui.ok("Test başarılı.")
            return candidate

        ui.warn(f"Test başarısız: {detail}")
        choice = _ask_choice(["Tekrar gir", "Yine de kaydet", "Atla"])
        if choice == 0:
            working_current = candidate
            continue
        if choice == 1:
            return candidate
        return None


def _write_block(env_path: Path, env_map: dict[str, str], values: dict[str, str]) -> None:
    updates: dict[str, str] = {}
    for field, env_key in env_map.items():
        if field == "headers":
            updates[env_key] = _encode_headers(values.get(field, ""))
        else:
            updates[env_key] = values.get(field, "")
    envio.write_env_updates(env_path, updates)


def _encode_headers(raw: str) -> str:
    import json

    try:
        parsed = providers.parse_headers(raw)
    except ValueError:
        parsed = {}
    return json.dumps(parsed, ensure_ascii=False)


def run(root: Path, *, backend_in_scope: bool) -> None:
    if not backend_in_scope:
        return

    backend_env = root / "backend" / ".env"
    env = envio.read_env_file(backend_env)

    ui.step("Yapılandırma sihirbazı")
    ui.info(
        "Şimdi Flash/Pro/embedding model ayarlarını gireceğiz. "
        "Her adımda 's' yazarak o adımı atlayabilirsin."
    )

    skipped: list[str] = []

    flash_current = {key: env.get(env_key, "") for key, env_key in FLASH_ENV_MAP.items()}
    flash_result = _run_block(
        "Flash model", _MODEL_FIELDS, _MODEL_SECRET_FIELDS, flash_current, required=True, test_fn=_test_chat
    )
    if flash_result is not None:
        _write_block(backend_env, FLASH_ENV_MAP, flash_result)
    else:
        skipped.append("flash")

    ui.step("Pro model")
    pro_result: dict[str, Any] | None = None
    if flash_result and ui.confirm("Flash ile aynı ayarlar kullanılsın mı?", default=False):
        pro_result = dict(flash_result)
        ui.ok("Pro, Flash ile aynı ayarlanacak.")
    else:
        pro_current = {key: env.get(env_key, "") for key, env_key in PRO_ENV_MAP.items()}
        pro_result = _run_block(
            "Pro model (opsiyonel)",
            _MODEL_FIELDS,
            _MODEL_SECRET_FIELDS,
            pro_current,
            required=False,
            test_fn=_test_chat,
        )
    if pro_result is not None:
        _write_block(backend_env, PRO_ENV_MAP, pro_result)
    else:
        skipped.append("pro")

    embedding_current = {key: env.get(env_key, "") for key, env_key in EMBEDDING_ENV_MAP.items()}
    embedding_result = _run_block(
        "Embedding (hafıza için, opsiyonel)",
        _EMBEDDING_FIELDS,
        _EMBEDDING_SECRET_FIELDS,
        embedding_current,
        required=False,
        test_fn=_test_embedding,
    )
    if embedding_result is not None:
        _write_block(backend_env, EMBEDDING_ENV_MAP, embedding_result)
    else:
        skipped.append("embedding")

    ui.step("Yapılandırma özeti")
    if "flash" in skipped:
        ui.warn("Flash atlandı -- doldurulmadan backend başlamaz: `rona edit model flash`")
    else:
        ui.ok("Flash ayarlandı.")
    if "pro" in skipped:
        ui.info("Pro atlandı (opsiyonel): `rona edit model pro`")
    else:
        ui.ok("Pro ayarlandı.")
    if "embedding" in skipped:
        ui.info("Embedding atlandı (opsiyonel, hafıza aracı için gerekli): `rona edit model embedding`")
    else:
        ui.ok("Embedding ayarlandı.")
