"""tr/en runtime language for the `rona` CLI's own output (help text,
prompts, messages).

Independent from the backend's ``LANGUAGE`` and the web dashboard's
``UI_LANGUAGE`` -- each of the three lives in a different place on
purpose (see the language plan's "Ortak sözleşme" table) -- but they
share the same catalog shape and resolution style so `rona edit lang`
can treat all three uniformly.

Resolution order: ``RONA_LANG`` environment variable -> ``"language"`` in
``~/.rona/config.json`` (written by the installer, or by `rona edit
lang`) -> ``DEFAULT_LANGUAGE``.

``set_language(resolve_language())`` must run at the very top of
``main()``, before ``build_parser()`` -- argparse bakes ``help=``/
``description=`` strings in at parser-construction time, so the active
language has to be settled first. Every ``register()`` function's
``t(...)`` calls therefore run *after* the language is set, not at
import time.
"""

from __future__ import annotations

import json
import os

from rona_cli.locales import en, tr
from rona_cli.paths import state_file

DEFAULT_LANGUAGE = "tr"
SUPPORTED = ("tr", "en")

_CATALOGS: dict[str, dict[str, str]] = {"tr": tr.STRINGS, "en": en.STRINGS}
_active = DEFAULT_LANGUAGE


def _language_from_state() -> str | None:
    path = state_file()
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    lang = data.get("language")
    return lang if lang in SUPPORTED else None


def resolve_language() -> str:
    """``RONA_LANG`` -> ``~/.rona/config.json``'s ``"language"`` -> ``DEFAULT_LANGUAGE``."""
    env_lang = os.environ.get("RONA_LANG")
    if env_lang in SUPPORTED:
        return env_lang
    return _language_from_state() or DEFAULT_LANGUAGE


def set_language(lang: str) -> None:
    global _active
    _active = lang if lang in SUPPORTED else DEFAULT_LANGUAGE


def get_language() -> str:
    return _active


def t(key: str, **kwargs: object) -> str:
    """Look up ``key`` in the active language's catalog; fall back to the
    other language, then to the bare key itself, if it's missing."""
    template = _CATALOGS.get(_active, _CATALOGS[DEFAULT_LANGUAGE]).get(key)
    if template is None:
        other = "en" if _active == "tr" else "tr"
        template = _CATALOGS[other].get(key, key)
    return template.format(**kwargs) if kwargs else template
