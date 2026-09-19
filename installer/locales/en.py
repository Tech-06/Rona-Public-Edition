"""English strings for the installer. Must define exactly the same key
set as `tr.py` (enforced by tests/test_i18n.py).
"""

from __future__ import annotations

STRINGS: dict[str, str] = {
    # -- shared --------------------------------------------------------------
    "common.empty": "(empty)",
    "common.cancelled": "Cancelled.",
    # -- ui.py -----------------------------------------------------------------
    "ui.confirm_default_yes_suffix": "[Y/n]",
    "ui.confirm_default_no_suffix": "[y/N]",
    "ui.confirm_yes_words": "y,yes,e,evet",
    "ui.select_components_prompt": "Choose the components to install (type a number + Enter to toggle, blank line to confirm)",
    # -- main.py ---------------------------------------------------------------
    "main.python_too_old": "Python {min_major}.{min_minor}+ is required, found: {found_major}.{found_minor}.",
    "main.git_not_found": "git not found (not required for this install, informational only).",
    "main.no_components_selected": "No components selected, exiting.",
    "main.node_required": "The web dashboard can't be installed without Node.js (or drop it with --components).",
    "main.auth_token_set": "AUTH_TOKEN set (the backend and web .env files match).",
    "main.step_precheck": "Pre-checks",
    "main.step_summary": "Summary",
    "main.status_done": "done",
    "main.status_failed": "failed",
    "main.result_line": "{name}: {status}",
    "main.next_steps_heading": "Next steps:",
    "main.next_step_model": "  rona edit model flash   # required: enter your Flash model details",
    "main.repair_none_found": "No installed component found to repair.",
    "main.unknown_components": "Unknown component(s): {names}",
    "main.status_reinstall": "installed — will be reinstalled",
    "main.label_cli": "CLI      rona management tool",
    "main.label_backend": "Backend  Rona core (:8000)",
    "main.label_web": "Web      Web dashboard (:8016)",
    # -- prereq.py -----------------------------------------------------------------
    "prereq.no_package_manager": "{name} was not found and no package manager was detected for an automatic install.",
    "prereq.install_manually": "Install {name} by hand, then run the script again.",
    "prereq.not_found": "{name} not found.",
    "prereq.will_run": "This command will run: {command}",
    "prereq.confirm_install": "Install {name}?",
    "prereq.install_failed_exc": "{name} installation failed: {exc}",
    "prereq.install_failed_code": "{name} installation failed (exit code {code}).",
    "prereq.installed_ok": "{name} installed.",
    "prereq.installed_not_on_path": (
        "{name} was installed but doesn't appear on PATH in this session yet. "
        "Open a new terminal and run the script again."
    ),
    # -- steps/*.py: text shared verbatim by all three components -------------------
    "steps.common.removing_venv": "Removing the existing virtual environment...",
    "steps.common.creating_venv": "Creating a virtual environment...",
    "steps.common.venv_create_failed": "Could not create the virtual environment.",
    "steps.common.deps_failed": "Dependency installation failed.",
    # -- steps/cli.py -----------------------------------------------------------------
    "steps.cli.title": "CLI (rona)",
    "steps.cli.installing": "Installing rona-cli (pip install -e .)...",
    "steps.cli.install_failed": "rona-cli installation failed.",
    "steps.cli.done": "rona CLI installed.",
    # -- steps/backend.py -----------------------------------------------------------------
    "steps.backend.title": "Backend",
    "steps.backend.installing_deps": "Installing dependencies (this can take a while)...",
    "steps.backend.preparing_db": "Preparing the database...",
    "steps.backend.db_failed": "Database preparation failed.",
    "steps.backend.done": "Backend installed.",
    # -- steps/web.py -----------------------------------------------------------------
    "steps.web.title": "Web dashboard",
    "steps.web.installing_deps": "Installing dependencies...",
    "steps.web.npm_not_found": "npm not found; the web dashboard could not be built.",
    "steps.web.installing_frontend_deps": "Installing frontend dependencies ({cmd})...",
    "steps.web.npm_install_failed": "npm install/ci failed.",
    "steps.web.building_frontend": "Building the frontend (npm run build)...",
    "steps.web.npm_build_failed": "npm run build failed.",
    "steps.web.done": "Web dashboard installed.",
    # -- pathsetup.py -----------------------------------------------------------------
    "pathsetup.windows_exe_missing": "rona.exe not found, skipping PATH setup.",
    "pathsetup.already_on_path": "rona is already on PATH ({bin_dir}).",
    "pathsetup.windows_added": "rona added to PATH ({bin_dir}). Open a new terminal for the change to take effect.",
    "pathsetup.posix_script_missing": "rona script not found, skipping PATH setup.",
    "pathsetup.posix_not_on_path": "{bin_dir} is not on PATH.",
    "pathsetup.posix_will_add_line": "This line will be added to {rc_file}:",
    "pathsetup.posix_confirm_add": "Add it?",
    "pathsetup.posix_manual_hint": "To add it by hand: {line}",
    "pathsetup.posix_rc_updated": (
        "{rc_file} updated. Open a new terminal, or run `source {rc_file}`, for the change to take effect."
    ),
    "pathsetup.windows_removed": "rona removed from PATH ({bin_dir}).",
    "pathsetup.windows_not_on_path": "rona wasn't on PATH anyway ({bin_dir}).",
    "pathsetup.posix_shim_removed": "rona script removed ({shim_path}).",
    "pathsetup.posix_shim_not_found": "rona script was already gone ({shim_path}).",
    "pathsetup.posix_confirm_remove_rc": "Remove the line added to {rc_file}?",
    "pathsetup.posix_rc_left_untouched": "{rc_file} left untouched.",
    "pathsetup.posix_rc_cleaned": "Removed from {rc_file}.",
    # -- wizard.py -----------------------------------------------------------------
    "wizard.field_name": "Model name",
    "wizard.field_url": "API base URL",
    "wizard.field_key": "API key",
    "wizard.field_headers": "Extra HTTP headers (JSON, blank = none)",
    "wizard.embedding_field_key": "Google API key",
    "wizard.embedding_field_name": "Embedding model name",
    "wizard.invalid_choice": "Invalid choice.",
    "wizard.required_hint": "required, but",
    "wizard.optional_hint": "optional;",
    "wizard.step_hint": "This step is {hint} you can skip it by typing 's'.",
    "wizard.test_ok": "Test succeeded.",
    "wizard.test_failed": "Test failed: {detail}",
    "wizard.choice_retry": "Try again",
    "wizard.choice_save_anyway": "Save anyway",
    "wizard.choice_skip": "Skip",
    "wizard.title": "Configuration wizard",
    "wizard.intro": (
        "We'll now enter the Flash/Pro/embedding model settings. "
        "At each step, type 's' to skip it."
    ),
    "wizard.section_flash": "Flash model",
    "wizard.pro_heading": "Pro model",
    "wizard.pro_same_as_flash": "Use the same settings as Flash?",
    "wizard.pro_same_ok": "Pro will be set the same as Flash.",
    "wizard.section_pro": "Pro model (optional)",
    "wizard.section_embedding": "Embedding (for memory, optional)",
    "wizard.summary_title": "Configuration summary",
    "wizard.summary_flash_skipped": "Flash skipped -- the backend won't start until it's filled in: `rona edit model flash`",
    "wizard.summary_flash_ok": "Flash configured.",
    "wizard.summary_pro_skipped": "Pro skipped (optional): `rona edit model pro`",
    "wizard.summary_pro_ok": "Pro configured.",
    "wizard.summary_embedding_skipped": "Embedding skipped (optional, needed for the memory tool): `rona edit model embedding`",
    "wizard.summary_embedding_ok": "Embedding configured.",
    # -- steps/tools.py -----------------------------------------------------------
    "tools_step.title": "Optional tool packages",
    "tools_step.git_missing": (
        "git not found, skipping tool package installation "
        "(you can install one later with `rona tools install <id>`)."
    ),
    "tools_step.catalog_unreachable": "Could not reach the tool package catalog, skipping this step.",
    "tools_step.none_selected": "No packages selected.",
    "tools_step.installing": "Installing {id}...",
    "tools_step.installed_summary": "Installed packages: {ids}",
    "tools_step.failed_summary": "Packages that failed to install: {ids}",
    # -- uninstall.py (new) -----------------------------------------------------------
    "uninstall.item_environments": "Environments (virtual envs, node_modules, built dashboard)",
    "uninstall.item_path": "PATH integration (the rona command)",
    "uninstall.item_state": "Install state (~/.rona/config.json)",
    "uninstall.item_user_data": "User data (.env files, database, log)",
    "uninstall.item_tool_packages": "Installed tool packages",
    "uninstall.item_runtime": "Runtime artifacts (pid, lock, log files)",
    "uninstall.title": "Rona uninstall",
    "uninstall.nothing_found": "Nothing found to remove.",
    "uninstall.process_running": "{label} appears to be running (pid {pid}).",
    "uninstall.confirm_stop": "Stop {label}?",
    "uninstall.process_stopped": "{label} stopped.",
    "uninstall.items_required": "In non-interactive mode, use --items to specify what to remove.",
    "uninstall.unknown_items": "Unknown item(s): {names}",
    "uninstall.none_selected": "Nothing selected, exiting.",
    "uninstall.user_data_warning": (
        "User data includes API keys, memories, people and tasks, "
        "and will be deleted irreversibly."
    ),
    "uninstall.confirm_user_data": "Really delete user data?",
    "uninstall.user_data_kept": "User data kept.",
    "uninstall.done": "Removed: {items}",
    "uninstall.repo_kept_hint": "This folder (the repo) was not deleted; remove it by hand to clear the rest.",
}
