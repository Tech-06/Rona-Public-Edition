import sys
from pathlib import Path

import pytest

# Mirrors installer/main.py's own sys.path setup: `installer` is a plain
# top-level package (no pip install of its own), and envgen.py reuses
# rona_cli.envio from the sibling cli/ checkout.
REPO_ROOT = Path(__file__).resolve().parent.parent.parent
for _path in (str(REPO_ROOT), str(REPO_ROOT / "cli")):
    if _path not in sys.path:
        sys.path.insert(0, _path)

from installer import i18n


@pytest.fixture(autouse=True)
def _reset_installer_language():
    """`i18n._active` is process-global (set once per real run, in
    main()) -- any test that calls set_language/ask_language must not
    leak that choice into a test that runs after it and assumes tr."""
    yield
    i18n.set_language(i18n.DEFAULT_LANGUAGE)
