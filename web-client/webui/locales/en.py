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
}
