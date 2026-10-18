"""English strings for the web dashboard's BFF. This BFF was already
written in English before language support existed, so this file simply
restates the literal text that was already at each call site. `tr.py`
must define exactly the same key set (enforced by tests/test_i18n.py).
"""

from __future__ import annotations

STRINGS: dict[str, str] = {
    # -- host.py ---------------------------------------------------------------
    "webui.backend_dir_not_found": "Backend directory not found: {backend_dir}",
    "webui.already_running": "Backend already tracked as running",
    "webui.exited_immediately": "Backend exited immediately (code {code})",
    "webui.started_pid": "Started PID {pid}",
    "webui.not_tracked": "No backend process tracked by this web server",
    "webui.stop_requested": "Stop requested",
    "webui.restart_too_soon": "Restart requested too soon; wait a few seconds",
    # -- proxy.py ---------------------------------------------------------------
    "webui.backend_unreachable": "Backend is not reachable",
    "webui.backend_timeout": "Backend request timed out",
    "webui.backend_status_code": "status {code}",
    # -- server.py ---------------------------------------------------------------
    "webui.unsupported_content_type": "Unsupported content type",
    "webui.cross_site_blocked": "Cross-site request blocked",
    "webui.frontend_not_built": "Frontend not built",
    "webui.frontend_stale": (
        "The compiled frontend is older than its source (git pull without "
        "npm run build?); browsers are still getting the old UI. Run "
        "'rona web build', or 'npm ci && npm run build' in web-client/frontend."
    ),
    # -- package_jobs.py ---------------------------------------------------------
    "webui.invalid_package_id": "Invalid package id: {package_id}",
    "webui.package_job_busy": "Another package install/update/uninstall job is already running",
    "webui.backend_python_missing": "Backend python not found: {path}",
    "webui.manager_no_output": "The manager command produced no output",
    "webui.manager_timeout": "The manager command timed out",
    "webui.package_job_timed_out": "The package job timed out and was terminated",
    # -- auth.py (dashboard login) ----------------------------------------------
    "webui.login_required": "Login required",
    "webui.invalid_password": "Incorrect password",
    "webui.password_not_set": "No panel password is set; run 'rona web password' first",
    "webui.too_many_attempts": "Too many failed attempts; try again in {seconds} seconds",
    "webui.password_wrong_current": "Current password is incorrect",
    "webui.password_too_short": "The new password must be at least {min} characters",
    "webui.password_write_failed": "Could not save the new password",
    "webui.session_secret_ephemeral": (
        "WEB_SESSION_SECRET is empty; using a temporary one, so logins will not "
        "survive a restart. Run 'rona web password' to set a permanent one."
    ),
    "webui.public_without_password": (
        "Refusing to start: WEB_HOST is {host} (not loopback) but no panel "
        "password is set. Run 'rona web password' first."
    ),
    "webui.panel_locked_warning": (
        "No panel password is set; the dashboard stays locked until you run "
        "'rona web password'."
    ),
}
