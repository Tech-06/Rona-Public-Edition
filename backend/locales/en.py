"""English strings for the backend. Must define exactly the same key set
as `tr.py` (enforced by tests/test_i18n.py). Most of the backend was
already written in English before language support existed -- see the
language plan's context note -- so several of these simply restate what
was already the literal text at that call site.
"""

from __future__ import annotations

STRINGS: dict[str, str] = {
    # -- prompts/persona.md's language directive (see app/prompts.py) -----------
    "prompt.primary_language_rule": (
        "Your default language is English. However, if the user explicitly "
        "writes in another language, you must seamlessly adapt and respond "
        "in that language."
    ),
    # -- the worked example inside prompts/trigger.md and trigger/executor.py's
    # REPORTER_SYSTEM_PROMPT -- a plausible greeting in the active language,
    # so the few-shot example doesn't anchor the model to a fixed language.
    "prompt.example_greeting": "How are you?",
    # -- app/main.py --------------------------------------------------------------
    "main.recursion_limit_reply": (
        "This request needed far more tool steps than expected and I hit the "
        "turn limit. Could you narrow the request down a bit, or tell me "
        "where you'd like me to pick up from?"
    ),
    "main.auth_invalid_token": "Invalid or missing bearer token",
    "main.model_call_failed": "Model call failed: {exc}",
    "main.log_reconcile_failed": "conversation registry reconcile failed",
    "main.log_history_record_failed": "failed to record chat history for a turn",
    # -- app/dashboard.py -----------------------------------------------------------
    "dashboard.not_editable": "Not editable: {names}",
    "dashboard.task_not_found": "Task not found",
    "dashboard.run_not_found": "Run not found",
    "dashboard.invalid_kind": "invalid kind: {kind}",
    "dashboard.run_not_reported": "Run has not been reported to the user yet",
    "dashboard.graph_not_ready": "Graph is not ready",
    "dashboard.conversation_busy": "Conversation is busy",
    "dashboard.history_not_found": "Conversation not found",
    "dashboard.folder_not_found": "Folder not found",
    "dashboard.history_unavailable": "Chat history is unavailable",
    "dashboard.memory_not_found": "Memory #{id} not found.",
    "dashboard.archived_memory_not_found": "Archived memory #{id} not found.",
    "dashboard.person_not_found": "Person #{id} not found.",
    "dashboard.note_not_found": "Note #{id} not found.",
    "dashboard.notes_not_installed": "The notes package is not installed.",
    "dashboard.invalid_layer": "Invalid layer: {layer}. Use deep, seasonal or short.",
    "dashboard.consolidation_busy": "A memory consolidation run is already in progress.",
    # -- trigger/executor.py: outcome text stored on a task run -------------------------
    "trigger.outcome_timeout": "The run timed out after {minutes} minutes.",
    "trigger.outcome_condition_not_met": "The condition was not met.",
    "trigger.outcome_reported_failure": "The task reported failure.",
    "trigger.outcome_abnormal_end": "The action was executed, but the run ended abnormally: {loop_error}",
    "trigger.outcome_empty_message": "The executor returned an empty or invalid final message.",
    "trigger.outcome_not_active": "The task was not active when the run started.",
    "trigger.outcome_deactivated": "The task was deactivated during execution.",
    # -- trigger/executor.py: log lines --------------------------------------------------
    "trigger.log_round": "[trigger] %s attempt %d round %d llm %.1fs",
    "trigger.log_report_ok": "[trigger] %s report ok (summary %d chars)",
    "trigger.log_report_fallback": "[trigger] %s report fallback, raw reporter content: %r",
    "trigger.log_reporter_failed": "[trigger] %s reporter failed: %s",
    "trigger.log_completed": "[trigger] %s completed (attempt %d)",
    "trigger.log_attempt_failed": "[trigger] %s attempt %d failed: %s",
    "trigger.log_failed_after_attempts": "[trigger] %s failed after %d attempts",
    "trigger.log_persist_failure_failed": "[trigger] %s could not persist failure: %s",
    "trigger.log_failed": "[trigger] %s failed: %s",
    "trigger.log_fire_skipped_inactive": "[trigger] %s fire skipped (task not active)",
    "trigger.log_fire_skipped_running": "[trigger] %s fire skipped (previous occurrence still running)",
    "trigger.log_fired": "[trigger] %s fired: %s",
    "trigger.log_fire_failed": "[trigger] fire failed for %s: %s",
    # -- trigger/scheduler.py: log lines ---------------------------------------------------
    "trigger.log_missed": "[trigger] %s missed: %s",
    "trigger.log_missed_event_failed": "[trigger] missed-event handling failed for %s: %s",
    "trigger.log_db_not_found": "[trigger] database not found, no tasks registered",
    "trigger.log_register_failed": "[trigger] failed to register %s (%s): %s",
    "trigger.log_scheduled_count": "[trigger] %d active task(s) scheduled",
    # -- subagents/runner.py: outcome text stored on a subagent run -----------------------
    "subagent.outcome_empty_message": "The subagent model returned an empty final message.",
    "subagent.outcome_cancelled": "Task was cancelled before completion.",
    "subagent.outcome_timeout": "Task timed out after {seconds} seconds.",
    # -- subagents/runner.py: log lines -----------------------------------------------------
    "subagent.log_round": "[subagent] %s round %d llm %.1fs",
    "subagent.log_completed": "[subagent] %s completed (%s)",
    "subagent.log_timed_out": "[subagent] %s timed out (%s)",
    "subagent.log_failed": "[subagent] %s failed (%s): %s",
    "subagent.log_started": "[subagent] %s started (%s)",
    # -- toolbox/*.py: log lines --------------------------------------------------------------
    "toolbox.log_skip_tool": "toolbox: skipping tool from package '%s': %s",
    "toolbox.log_skip_package": "toolbox: skipping package in %s: %s",
    # -- graph/threads.py: log lines -----------------------------------------------------------
    "graph.log_purge_failed": "conversation purge failed for %s",
    # -- memory/ (Konsolidasyon): schema self-heal and consolidation log lines ------------
    "memory.log_schema_upgraded": "[memory] memories table upgraded, added columns: %s",
    "memory.log_schema_failed": "[memory] schema check failed: %s",
    "memory.log_access_failed": "[memory] could not record memory access: %s",
    "memory.log_promoted": "[memory] #%d promoted %s -> %s (%d hits): %s",
    "memory.log_archived": "[memory] #%d archived (%s, reason: %s): %s",
    "memory.log_deleted": "[memory] #%d deleted (short, %d hits): %s",
    "memory.log_run_done": (
        "[memory] consolidation (%s) finished: %d promoted to seasonal, "
        "%d promoted to deep, %d archived, %d deleted"
    ),
    "memory.log_run_failed": "[memory] consolidation (%s) failed: %s",
    "memory.log_scheduler_started": "[memory] consolidation scheduler started (every %d h)",
    "memory.log_scheduler_disabled": (
        "[memory] automatic consolidation is off (MEMORY_CONSOLIDATION_INTERVAL_HOURS=0)"
    ),
    "memory.log_scheduler_error": "[memory] consolidation scheduler error: %s",
    "memory.log_person_memories_archived": (
        "[memory] person #%d deleted, %d linked memories archived"
    ),
}
