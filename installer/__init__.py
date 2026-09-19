"""Rona's cross-platform, stdlib-only installer.

Bootstrapped by ``install.ps1`` (Windows) / ``install.sh`` (macOS, Linux),
which only ensure a Python 3.11+ interpreter is on PATH before handing off
to ``installer/main.py``. Everything else -- component selection, Node/Git
prerequisites, venvs, .env generation, the npm build -- lives here.
"""
