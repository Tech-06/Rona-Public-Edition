"""Small terminal UI helpers for the installer: step headers and a
numbered toggle-menu for choosing which components to install.

No curses/arrow-key navigation on purpose -- this has to work identically
in a plain cmd.exe console with zero extra dependencies, right after a
fresh clone, before anything beyond the stdlib is available.
"""

from __future__ import annotations

import sys

_NO_COLOR = not sys.stdout.isatty()
_RESET = "\033[0m"
_COLORS = {
    "green": "\033[32m",
    "red": "\033[31m",
    "yellow": "\033[33m",
    "bold": "\033[1m",
    "cyan": "\033[36m",
}


def _paint(text: str, color: str) -> str:
    return text if _NO_COLOR else f"{_COLORS[color]}{text}{_RESET}"


def step(title: str) -> None:
    print(flush=True)
    print(_paint(f"== {title} ==", "bold"), flush=True)


def ok(message: str) -> None:
    print(f"{_paint('[OK]', 'green')} {message}", flush=True)


def warn(message: str) -> None:
    print(f"{_paint('[!]', 'yellow')} {message}", flush=True)


def error(message: str) -> None:
    print(f"{_paint('[X]', 'red')} {message}", file=sys.stderr, flush=True)


def info(message: str = "") -> None:
    print(message, flush=True)


def confirm(prompt: str, default: bool = False) -> bool:
    suffix = "[E/h]" if default else "[e/H]"
    try:
        answer = input(f"{prompt} {suffix} ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        print()
        return False
    if not answer:
        return default
    return answer in ("e", "evet", "y", "yes")


def select_components(options: list[tuple[str, str, bool, str]]) -> list[str]:
    """``options``: list of (id, label, default_selected, status_note).

    Prints a numbered list with `[x]`/`[ ]` markers; typing space/comma
    separated numbers toggles their selection, an empty line confirms.
    Returns the selected ids, in the original option order.
    """
    selected = {opt_id for opt_id, _, default, _ in options if default}
    while True:
        print(flush=True)
        info("Kurulacak bileşenleri seç (numara yaz + Enter: seç/kaldır, boş satır: onayla)")
        for index, (opt_id, label, _default, note) in enumerate(options, start=1):
            mark = "x" if opt_id in selected else " "
            suffix = f"  ({note})" if note else ""
            info(f"  [{mark}] {index}) {label}{suffix}")
        try:
            raw = input("> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            raw = ""
        if not raw:
            break
        for token in raw.replace(",", " ").split():
            if not token.isdigit():
                continue
            index = int(token)
            if 1 <= index <= len(options):
                opt_id = options[index - 1][0]
                if opt_id in selected:
                    selected.discard(opt_id)
                else:
                    selected.add(opt_id)
    return [opt_id for opt_id, *_ in options if opt_id in selected]
