"""English strings for the `rona` CLI. Must define exactly the same key
set as `tr.py` (enforced by tests/test_i18n.py) -- `rona_cli.i18n.t()`
falls back to the other language, then to the bare key, if one is ever
missing here.
"""

from __future__ import annotations

STRINGS: dict[str, str] = {
    # -- shared across multiple commands -----------------------------------
    "common.empty": "(empty)",
    "common.cancelled": "Cancelled.",
    "common.help_skip_confirm": "skip confirmation",
    "common.help_person_id": "person id",
    "common.help_json_object": "JSON object",
    "common.metadata_invalid_json": "metadata is not a valid JSON object: {exc}",
    # -- ui.py ---------------------------------------------------------------
    "ui.confirm_default_yes_suffix": "[Y/n]",
    "ui.confirm_default_no_suffix": "[y/N]",
    "ui.confirm_yes_words": "y,yes,e,evet",
    # -- cli.py ---------------------------------------------------------------
    "cli.help_root": "root folder of the Rona installation (default: auto-detected)",
    "cli.help_json": "print output as JSON",
    "cli.description": "Tool for managing a Rona installation from the terminal.",
    # -- paths.py ---------------------------------------------------------------
    "paths.invalid_root": (
        "'{candidate}' doesn't look like a Rona installation "
        "(expected backend/ and web-client/ subfolders)."
    ),
    "paths.not_found": (
        "Could not find a Rona installation. Pass `rona --root <path>`, "
        "set the RONA_HOME environment variable, or run the install script."
    ),
    "paths.venv_missing": "Virtual environment not found: {venv_dir}. Run the install script or create it by hand.",
    # -- backend_client.py -----------------------------------------------------
    "backend_client.no_auth_token": "AUTH_TOKEN is not set; run `rona edit auth reset` first.",
    "backend_client.unreachable": "Could not reach the backend ({exc}); run `rona server start` first.",
    # -- http.py ---------------------------------------------------------------
    "http.connection_failed": "could not connect: {reason}",
    "http.timeout": "the request timed out",
    # -- providers.py ------------------------------------------------------------
    "providers.chat_missing_fields": "url, key and model name are required",
    "providers.embedding_missing_fields": "api key and model name are required",
    "providers.headers_invalid_json": "headers is not valid JSON: {exc}",
    "providers.headers_not_object": "headers must be a JSON object",
    # -- commands/status.py ------------------------------------------------------
    "status.heading": "Rona installation: {root}",
    "status.backend_running": "Backend  running  (uptime {uptime}s, model {model})",
    "status.backend_stopped": "Backend  stopped  ({detail})",
    "status.web_running": "Web      running  (pid {pid}, uptime {uptime}s)",
    "status.web_stopped": "Web      stopped  ({detail})",
    "status.packages_installed": "Installed tool packages ({count}): {packages}",
    "status.no_packages": "No tool packages installed.",
    "status.tools_hint": "Details: `rona tools list` -- to configure one: `rona tools config <package>`",
    "status.help": "Show backend, web and tool package status",
    # -- commands/server.py -------------------------------------------------------
    "server.no_auth_token": "AUTH_TOKEN is not set",
    "server.already_running": "backend is already running",
    "server.systemctl_start_failed": "systemctl start failed",
    "server.exited_immediately": "backend exited immediately (exit code {code}); {tail}",
    "server.started": "backend started at {host}:{port}",
    "server.start_timeout": "backend did not become healthy in time (check `rona log tail`)",
    "server.already_stopped": "backend is already stopped",
    "server.systemctl_stop_failed": "systemctl stop failed",
    "server.stop_no_pid": (
        "no process to stop was found (no pid file); the backend may have "
        "been started outside of rona, you'll need to stop it by hand"
    ),
    "server.stopped": "backend stopped",
    "server.stop_timeout": "backend did not stop in time",
    "server.status_running": "Backend running at {host}:{port} (uptime {uptime}s, model {model})",
    "server.pro_configured": "configured",
    "server.pro_not_configured": "not configured",
    "server.scheduler_running": "running",
    "server.scheduler_stopped": "stopped",
    "server.status_detail": "         pro model: {pro}, scheduler: {scheduler}",
    "server.status_stopped": "Backend is stopped ({detail})",
    "server.help_group": "Manage the backend process",
    "server.help_start": "Start the backend process",
    "server.help_stop": "Stop the backend process",
    "server.help_restart": "Restart the backend process",
    "server.help_status": "Show the backend process's status",
    # -- commands/web.py -----------------------------------------------------------
    "web.status_running": "Web dashboard running at {host}:{port} (pid {pid}, uptime {uptime}s)",
    "web.status_stopped": "Web dashboard is stopped ({detail})",
    "web.help_group": "Manage the web dashboard",
    "web.help_start": "Start the web dashboard",
    "web.help_stop": "Stop the web dashboard",
    "web.help_restart": "Restart the web dashboard",
    "web.help_status": "Show the web dashboard's status",
    "web.frontend_stale": (
        "The compiled frontend is older than its source -- browsers still get the old UI "
        "(not rebuilt after git pull). To rebuild: cd {path} && npm ci && npm run build"
    ),
    # -- commands/edit/__init__.py --------------------------------------------------
    "edit.help_group": "Edit configuration",
    # -- commands/edit/auth.py -------------------------------------------------------
    "auth.confirm_reset": (
        "Generate a new AUTH_TOKEN and write it to both backend and web .env files? "
        "Running processes will need to be restarted."
    ),
    "auth.restart_hint": "Run `rona server restart` and `rona web restart` for the change to take effect.",
    "auth.reset_ok": "New AUTH_TOKEN written to the backend and web .env files.",
    "auth.empty_token": "token cannot be empty",
    "auth.set_ok": "AUTH_TOKEN written to the backend and web .env files.",
    "auth.help_group": "Manage the shared AUTH_TOKEN",
    "auth.help_get": "Show the current token",
    "auth.help_show_flag": "show the token unmasked",
    "auth.help_reset": "Generate a new random token",
    "auth.help_set": "Set a specific token",
    # -- commands/edit/env.py ---------------------------------------------------------
    "env.creating": "{path} does not exist yet; creating it.",
    "env.editor_failed": "Could not run the editor: {command}",
    "env.open_manually": "Open the file by hand: {path}",
    "env.help_group": "Open a .env file in your editor",
    "env.help_backend_flag": "open backend/.env (default)",
    "env.help_web_flag": "open web-client/.env",
    # -- commands/edit/model.py -------------------------------------------------------
    "model.heading": "{target} model settings",
    "model.prompt_field": "  {field} [{shown}] (leave blank = keep): ",
    "model.embedding_ignored_flag": "--{flag} is ignored for the embedding target",
    "model.confirm_save_despite_failure": "Test failed ({detail}). Save anyway?",
    "model.test_failed": "test failed: {detail}",
    "model.test_ok": "Test succeeded.",
    "model.saved": "{target} settings saved. Run `rona server restart` for the change to take effect.",
    "model.help_group": "Edit the Flash/Pro/embedding model settings",
    "model.help_target": "which model tier to edit",
    "model.help_name": "model name",
    "model.help_url": "API base URL (flash/pro)",
    "model.help_key": "API key",
    "model.help_headers": "extra HTTP headers (JSON, flash/pro)",
    "model.help_test": "verify with a real API call before saving",
    # -- commands/edit/memory.py -------------------------------------------------------
    "memory.no_results": "No results.",
    "memory.result_line": "[{id}] ({layer}, score {score}) {content}",
    "memory.added": "Memory added (id {id}).",
    "memory.edit_no_fields": "specify at least one field to change (--layer/--content/--person/--metadata)",
    "memory.updated": "Memory updated.",
    "memory.confirm_delete": "Delete memory #{id}?",
    "memory.deleted": "Memory deleted.",
    "memory.stats_total": "Total: {total}",
    "memory.stats_split": "General (no person): {general}, linked to a person: {linked}",
    "memory.stats_range": "Oldest: {oldest}, newest: {newest}",
    "memory.stats_access_count": "Total access count: {count}",
    "memory.help_group": "Manage memory records",
    "memory.help_search": "Run a semantic search",
    "memory.help_add": "Add a new memory",
    "memory.help_edit": "Edit an existing memory",
    "memory.help_delete": "Delete a memory",
    "memory.help_stats": "Show memory statistics",
    # -- commands/task.py -------------------------------------------------------------
    "task.no_tasks": "No tasks.",
    "task.list_line": "[{status:>7}] {id}  {name}  (next: {next_run})",
    "task.confirm_delete": "Delete task {id}?",
    "task.deleted": "Task deleted.",
    "task.toggled": "Task is now {status}.",
    "task.help_group": "Manage scheduled tasks",
    "task.help_list": "List tasks",
    "task.help_delete": "Delete a task",
    "task.help_toggle": "Toggle active/passive status",
    # -- commands/log.py --------------------------------------------------------------
    "log.no_records": "No records.",
    "log.confirm_delete": "Delete run {id}?",
    "log.delete_unreported": "the run has not been reported to the user yet; it must be read first",
    "log.deleted": "Run deleted.",
    "log.stream_broken": "Log stream broke: {exc}",
    "log.file_not_found": "Log file not found: {path}",
    "log.following_local": "Backend is not running; following the local log file.",
    "log.help_group": "Execution history and live log",
    "log.help_list": "List past runs",
    "log.help_unread_flag": "only runs not yet reported",
    "log.help_show": "Show one run's detail",
    "log.help_delete": "Delete a run that was already reported",
    "log.help_tail": "Follow the live log stream",
    "log.help_level_flag": "e.g. INFO, ERROR",
    "log.help_grep_flag": "text filter",
    # -- commands/edit/lang.py (new) ----------------------------------------------------
    "lang.help_group": "Show/set the language of all three components (backend, web, cli)",
    "lang.help_language_arg": "language to set (shows current languages if omitted)",
    "lang.help_backend_flag": "only set the backend",
    "lang.help_web_flag": "only set the web dashboard",
    "lang.help_cli_flag": "only set this CLI",
    "lang.current_backend": "Backend : {lang}",
    "lang.current_web": "Web     : {lang}",
    "lang.current_cli": "CLI     : {lang}",
    "lang.set_ok": "Language set to {language} ({changed}).",
    "lang.restart_hint": "Run `rona server restart` and `rona web restart` for the change to take effect.",
    # -- commands/tools.py (new) ----------------------------------------------------
    "tools.help_group": "Manage tool packages",
    "tools.help_list": "List installed tool packages",
    "tools.help_available": "List packages in the catalog",
    "tools.help_install": "Install a tool package",
    "tools.help_uninstall": "Uninstall a tool package",
    "tools.help_verify": "Re-run a package's health check",
    "tools.help_source_flag": "catalog source (local:/git:/https:)",
    "tools.help_set_flag": "pre-supply a config value (repeatable)",
    "tools.help_keep_flag": "install even if the health check fails",
    "tools.help_force_flag": "uninstall even if other packages depend on it",
    "tools.none_installed": "No tool packages installed.",
    "tools.catalog_empty": "No packages in the catalog.",
    "tools.manager_no_output": "No response from toolbox.manager.",
    "tools.help_config": "Show or change a package's configuration",
    "tools.help_config_set": "set one value (repeatable)",
    "tools.help_config_edit": "prompt for every field (blank keeps the current value)",
    "tools.help_actions": "List the operations a package exposes",
    "tools.help_run": "Run one of a package's operations",
    "tools.help_run_set": "supply an operation parameter (repeatable)",
    "tools.help_purge_flag": "also delete files you created (tokens etc.)",
    "tools.installed_marker": "installed",
    "tools.requires": "requires: {packages}",
    "tools.config_none": "'{package}' has no configuration.",
    "tools.config_not_set": "(not set)",
    "tools.config_secret_set": "(set)",
    "tools.config_changed": "{package}: updated {fields}.",
    "tools.restart_hint": "For the change to take effect: `rona server restart`",
    "tools.actions_none": "'{package}' exposes no operations.",
    "tools.action_destructive": "irreversible",
    "tools.action_cli_only": "terminal only",
    "tools.action_params": "parameters: {params}",
    "tools.run_hint": "To run one: `rona tools run {package} <operation>`",
}
