"""tr/en runtime language for this BFF's own user-facing strings --
the handful of literal messages in host.py/proxy.py/server.py that
surface directly in the dashboard UI (StatusPanel's action/detail text,
ErrorState's message), via `frontend/src/api/client.ts`'s `ApiError`.

Same dict-catalog/t(key, **kwargs) shape as the backend's own i18n.py
and the CLI's/installer's, but deliberately a separate, independent
catalog -- this is its own deployable component (see webui/config.py's
docstring) and must keep working without importing anything from
backend/ (test_webui_isolation.py enforces this).

The active language comes from Settings.ui_language (web-client/.env's
UI_LANGUAGE), read lazily inside t() the same way backend/i18n.py reads
Settings.language -- so a module that imports this one doesn't risk a
circular import through webui.config.
"""

from __future__ import annotations

from webui.locales import en, tr

DEFAULT_LANGUAGE = "tr"
SUPPORTED = ("tr", "en")

_CATALOGS: dict[str, dict[str, str]] = {"tr": tr.STRINGS, "en": en.STRINGS}


def _active_language() -> str:
    from webui.config import get_settings

    language = get_settings().ui_language
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
