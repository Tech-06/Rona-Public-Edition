"""Small terminal output helpers.

Uses plain ASCII tags (``[OK]``/``[!]``/``[X]``) instead of Unicode symbols
so output stays readable on a stock Windows console with no UTF-8 codepage
configured -- this tool is meant to work right after a fresh install.
"""

from __future__ import annotations

import os
import sys

_NO_COLOR = bool(os.environ.get("NO_COLOR")) or not sys.stdout.isatty()

_RESET = "\033[0m"
_COLORS = {
    "green": "\033[32m",
    "red": "\033[31m",
    "yellow": "\033[33m",
    "cyan": "\033[36m",
    "bold": "\033[1m",
}


def _paint(text: str, color: str) -> str:
    if _NO_COLOR:
        return text
    return f"{_COLORS[color]}{text}{_RESET}"


def ok(message: str) -> None:
    print(f"{_paint('[OK]', 'green')} {message}", flush=True)


def warn(message: str) -> None:
    print(f"{_paint('[!]', 'yellow')} {message}", flush=True)


def error(message: str) -> None:
    print(f"{_paint('[X]', 'red')} {message}", file=sys.stderr, flush=True)


def info(message: str = "") -> None:
    print(message, flush=True)


def heading(text: str) -> None:
    print(_paint(text, "bold"), flush=True)


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
