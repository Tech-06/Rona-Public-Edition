"""tr/en runtime language for backend-authored text that reaches a human:
the persona prompt's language directive, a couple of localized few-shot
example strings inside worker/reporter prompts, the literal strings
passed to ``HTTPException`` in ``app/main.py``/``app/dashboard.py``, the
outcome text stored on a failed task/subagent run, and operator-facing
log lines.

Deliberately NOT used by ``toolbox/tools/*.py``'s tool-function error
strings (``{"success": False, "error": ...}``) -- those are fed back to
the LLM as tool-call results, not shown to the user directly, and stay
English so the model sees a stable, unlocalized vocabulary of error
shapes regardless of the user's own language. Also not used for
exception text forwarded verbatim from a lower layer (a pydantic
validation error, a raised ``ValueError``'s ``str(exc)``) -- only the
literal strings this backend authors itself.

The active language comes from ``Settings.language`` (backend/.env's
``LANGUAGE``), read lazily inside :func:`t` rather than imported at
module level: almost every package in this backend (toolbox, trigger,
subagents, graph) can end up importing this module, and ``app.config``
itself sits low enough in that graph that a module-level ``from
app.config import get_settings`` here would risk a circular import the
first time some new caller is added elsewhere. Reading it lazily costs
nothing extra since ``get_settings()`` is itself ``lru_cache``'d.
"""

from __future__ import annotations

from locales import en, tr

DEFAULT_LANGUAGE = "tr"
SUPPORTED = ("tr", "en")

_CATALOGS: dict[str, dict[str, str]] = {"tr": tr.STRINGS, "en": en.STRINGS}


def _active_language() -> str:
    from app.config import get_settings

    language = get_settings().language
    return language if language in SUPPORTED else DEFAULT_LANGUAGE


def t(key: str, **kwargs: object) -> str:
    """Look up ``key`` in the active language's catalog; fall back to the
    other language, then to the bare key itself, if it's missing."""
    active = _active_language()
    template = _CATALOGS.get(active, _CATALOGS[DEFAULT_LANGUAGE]).get(key)
    if template is None:
        other = "en" if active == "tr" else "tr"
        template = _CATALOGS[other].get(key, key)
    return template.format(**kwargs) if kwargs else template
