"""tr/en runtime language for the installer's own output.

Independent from the backend's ``LANGUAGE``, the web dashboard's
``UI_LANGUAGE``, and the `rona` CLI's own catalog -- each lives and is
looked up separately (see the language plan's "Ortak sözleşme" table) --
but they share the same catalog shape.

Unlike ``rona_cli.i18n``, there's nothing to *resolve* here: this run's
language is either given on the command line (``--lang``) or asked
interactively via :func:`ask_language`, right at the start of
``installer.main.main()``, before anything else runs. ``set_language``
must be called before any ``t(...)`` lookup; every module that needs one
calls it from inside a function (never at import time), since import
happens before the language for this run is known.
"""

from __future__ import annotations

from installer.locales import en, tr

DEFAULT_LANGUAGE = "tr"
SUPPORTED = ("tr", "en")

_CATALOGS: dict[str, dict[str, str]] = {"tr": tr.STRINGS, "en": en.STRINGS}
_active = DEFAULT_LANGUAGE


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


def ask_language() -> str:
    """The very first prompt, before any language is chosen -- shown in
    both at once, since we don't yet know which one the user reads.
    EOF/interrupt defaults to DEFAULT_LANGUAGE, the same fallback
    ``ui.confirm`` uses elsewhere in this package."""
    print()
    print("Language / Dil")
    print("  1) Türkçe")
    print("  2) English")
    while True:
        try:
            raw = input("> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return DEFAULT_LANGUAGE
        if raw in ("", "1"):
            return "tr"
        if raw == "2":
            return "en"
        print("Geçersiz seçim / Invalid choice")
