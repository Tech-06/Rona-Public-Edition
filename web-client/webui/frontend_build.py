"""Detects a compiled frontend (webui/dist/) that is older than its source.

dist/ is gitignored and only produced by `npm run build`, so a plain
`git pull` updates frontend/src but leaves every browser on the old
bundle -- while the backend and this BFF are already running the new
code. That half-upgrade fails silently: the old UI simply never calls
whatever the new one would have (the shared chat history, for one).
This only compares file modification times, so it's cheap enough to run
on every /host/healthz call.
"""

from __future__ import annotations

from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
FRONTEND_DIR = ROOT_DIR / "frontend"
DIST_INDEX = Path(__file__).resolve().parent / "dist" / "index.html"

# What `npm run build` actually compiles. package-lock.json is left out on
# purpose: `npm install` can rewrite it without anything having changed
# that a rebuild would pick up.
_SOURCE_DIRS = ("src", "public")
_SOURCE_FILES = (
    "index.html",
    "package.json",
    "vite.config.ts",
    "tailwind.config.js",
    "postcss.config.js",
)


def _newest_source_mtime(frontend_dir: Path) -> float | None:
    newest: float | None = None
    for name in _SOURCE_DIRS:
        directory = frontend_dir / name
        if not directory.is_dir():
            continue
        for path in directory.rglob("*"):
            if path.is_file():
                mtime = path.stat().st_mtime
                newest = mtime if newest is None else max(newest, mtime)
    for name in _SOURCE_FILES:
        path = frontend_dir / name
        if path.is_file():
            mtime = path.stat().st_mtime
            newest = mtime if newest is None else max(newest, mtime)
    return newest


def is_stale(frontend_dir: Path = FRONTEND_DIR, dist_index: Path = DIST_INDEX) -> bool:
    """True when some frontend source file is newer than the last build.

    False when there is no build at all (the SPA fallback already reports
    that on its own) or no source checkout next to it (a deployment that
    only ships the prebuilt dist/).
    """
    if not dist_index.is_file():
        return False
    newest = _newest_source_mtime(frontend_dir)
    if newest is None:
        return False
    return newest > dist_index.stat().st_mtime
