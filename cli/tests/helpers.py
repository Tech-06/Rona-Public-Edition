"""Small shared helpers for CLI tests. Not a test module itself."""

from __future__ import annotations


def make_root(tmp_path):
    """A fake Rona checkout with the backend/ + web-client/ layout
    `rona_cli.paths.find_root` looks for."""
    root = tmp_path / "rona-checkout"
    (root / "backend").mkdir(parents=True)
    (root / "web-client").mkdir(parents=True)
    return root
