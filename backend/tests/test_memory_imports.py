"""Enforces memory/__init__.py's import rule: no module in backend/memory/
may import `toolbox` or `app` (specifically `app.config`, the thing that
would actually complete the cycle) at module level.

Runs in a subprocess with a clean sys.modules, rather than asserting on
the current process, because pytest's own collection has almost
certainly already imported toolbox/app.config for other test modules by
the time this one runs -- that would make the assertion meaningless here.

Discovers modules via pkgutil rather than hard-coding a list, so any
new memory/*.py module is covered automatically.
"""

import subprocess
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]

_SCRIPT = """
import pkgutil
import sys

import memory

for module_info in pkgutil.iter_modules(memory.__path__):
    __import__(f"memory.{module_info.name}")

assert "toolbox" not in sys.modules, "importing memory.* pulled in toolbox"
assert "app.config" not in sys.modules, "importing memory.* pulled in app.config"
print("OK")
"""


def test_memory_modules_do_not_import_toolbox_or_app_config_at_module_level():
    result = subprocess.run(
        [sys.executable, "-B", "-c", _SCRIPT],
        cwd=BACKEND_DIR,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert result.returncode == 0, (
        f"subprocess failed (exit {result.returncode})\n"
        f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    )
    assert "OK" in result.stdout
