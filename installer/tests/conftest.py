import sys
from pathlib import Path

# Mirrors installer/main.py's own sys.path setup: `installer` is a plain
# top-level package (no pip install of its own), and envgen.py reuses
# rona_cli.envio from the sibling cli/ checkout.
REPO_ROOT = Path(__file__).resolve().parent.parent.parent
for _path in (str(REPO_ROOT), str(REPO_ROOT / "cli")):
    if _path not in sys.path:
        sys.path.insert(0, _path)
