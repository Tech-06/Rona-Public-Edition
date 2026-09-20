"""Post-install step: optional tool packages from the Rona Tools catalog
(github.com/Tech-06/Rona-Tools by default -- see toolbox/sources.py's
DEFAULT_CATALOG_SOURCE). Runs only when the backend is part of this
installer run and the session is interactive -- the caller in main.py
gates on both before calling run() here, the same way it already gates
wizard.run(). Nothing here is required for a working installation, and
there's no sensible non-interactive default for "which optional tools
do you want", so every option starts unchecked (opt-in, not opt-out).

Delegates to the backend's own `python -m toolbox.manager`, exactly the
way `rona tools` (cli/rona_cli/commands/tools.py) does -- this module
and that one intentionally share the same two-mode pattern: --json
captured for the catalog listing, inherited stdio for the actual
installs, since a package's own config prompts (a secret via getpass,
the health-check retry/keep/cancel choice) need a live terminal.
"""

from __future__ import annotations

import json as jsonlib
import subprocess
from pathlib import Path

from installer import detect, i18n, ui


def _backend_python(root: Path) -> Path | None:
    python = detect.venv_python_path(root / "backend" / ".venv")
    return python if python.is_file() else None


def _fetch_catalog(python: Path, backend_dir: Path) -> list[dict] | None:
    result = subprocess.run(
        [str(python), "-m", "toolbox.manager", "--json", "available"],
        cwd=backend_dir,
        capture_output=True,
        text=True,
        check=False,
    )
    lines = result.stdout.strip().splitlines()
    try:
        payload = jsonlib.loads(lines[-1]) if lines else None
    except jsonlib.JSONDecodeError:
        payload = None
    if payload is None or not payload.get("ok"):
        return None
    return payload.get("packages", [])


def run(root: Path) -> None:
    backend_dir = root / "backend"
    python = _backend_python(root)
    if python is None:
        return

    ui.step(i18n.t("tools_step.title"))

    if not detect.git_available():
        ui.warn(i18n.t("tools_step.git_missing"))
        return

    packages = _fetch_catalog(python, backend_dir)
    if not packages:
        ui.warn(i18n.t("tools_step.catalog_unreachable"))
        return

    # A library package (google_auth) provides no tools of its own and is
    # pulled in automatically by whatever requires it, so listing it among
    # "which tools do you want" only muddies the choice.
    offered = [pkg for pkg in packages if pkg.get("kind") != "library"]
    if not offered:
        ui.warn(i18n.t("tools_step.catalog_unreachable"))
        return

    options = []
    for pkg in offered:
        requires = pkg.get("requires") or []
        note = (
            i18n.t("tools_step.requires", packages=", ".join(requires)) if requires else ""
        )
        options.append((pkg["id"], f"{pkg['name']} — {pkg['description']}", False, note))
    selected = ui.select_components(options)
    if not selected:
        ui.info(i18n.t("tools_step.none_selected"))
        return

    installed: list[str] = []
    failed: list[str] = []
    for package_id in selected:
        ui.info(i18n.t("tools_step.installing", id=package_id))
        result = subprocess.run(
            [str(python), "-m", "toolbox.manager", "install", package_id],
            cwd=backend_dir,
            check=False,
        )
        (installed if result.returncode == 0 else failed).append(package_id)

    if installed:
        ui.ok(i18n.t("tools_step.installed_summary", ids=", ".join(installed)))
    if failed:
        ui.warn(i18n.t("tools_step.failed_summary", ids=", ".join(failed)))
