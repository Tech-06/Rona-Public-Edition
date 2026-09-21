import { tr } from "./tr";

// English strings for the web dashboard. Typed against `tr`'s key set --
// a missing or extra key here is a `tsc -b` build error, not a runtime
// surprise (see lib/i18n.ts).
export const en: Record<keyof typeof tr, string> = {
  // -- common (reused across several panels/sections) -------------------------------
  "common.save": "Save",
  "common.saving": "Saving...",
  "common.save_failed": "Could not save",
  "common.action_failed": "Action failed",
  "common.configured": "configured",

  // -- settings/AppearanceSection.tsx -------------------------------------------------
  "appearance.theme_title": "Theme",
  "appearance.theme_description":
    "Choose whether the interface follows light, dark, or your operating system's setting.",
  "appearance.theme_system": "System",
  "appearance.theme_light": "Light",
  "appearance.theme_dark": "Dark",
  "appearance.language_title": "Language",
  "appearance.language_description":
    "Choose which language the dashboard is shown in. This only affects this browser.",
  "appearance.language_tr": "Türkçe",
  "appearance.language_en": "English",

  // -- lib/toolLabels.ts ---------------------------------------------------------------
  "tool.get_time": "Checking the time",
  "tool.web_search": "Searching the web",
  "tool.web_scraper": "Reading the page",
  "tool.get_weather": "Getting the weather",
  "tool.translate_text": "Translating",
  "tool.get_events": "Checking the calendar",
  "tool.add_event": "Adding to the calendar",
  "tool.edit_event": "Updating the calendar",
  "tool.delete_event": "Deleting from the calendar",
  "tool.get_contacts": "Scanning contacts",
  "tool.add_contact": "Adding a contact",
  "tool.edit_contact": "Updating a contact",
  "tool.delete_contact": "Deleting a contact",
  "tool.send_email": "Sending an email",
  "tool.get_recent_emails": "Scanning emails",
  "tool.add_note": "Saving a note",
  "tool.get_notes": "Checking notes",
  "tool.edit_note": "Updating a note",
  "tool.delete_note": "Deleting a note",
  "tool.add_person": "Adding a person",
  "tool.get_people": "Scanning people",
  "tool.edit_person": "Updating a person",
  "tool.delete_person": "Deleting a person",
  "tool.search_person": "Searching for a person",
  "tool.add_memory": "Writing to memory",
  "tool.get_memories": "Looking through memory",
  "tool.edit_memory": "Updating a memory",
  "tool.delete_memory": "Deleting from memory",
  "tool.search_memories": "Searching memory",
  "tool.start_subagent": "Starting a background agent",
  "tool.list_subagents": "Checking background agents",
  "tool.get_subagent_report": "Getting the agent's report",
  "tool.dismiss_subagent_report": "Dismissing the agent's report",
  "tool.create_task": "Scheduling a task",
  "tool.list_tasks": "Checking scheduled tasks",
  "tool.get_task": "Checking the task",
  "tool.update_task": "Updating the task",
  "tool.delete_task": "Deleting the task",
  "tool.get_task_run": "Checking the task's result",
  "tool.dismiss_task_run": "Dismissing the task notification",
  "tool.bb_get_courses": "Checking your courses",
  "tool.bb_get_announcements": "Checking announcements",
  "tool.bb_get_calendar": "Checking the Blackboard calendar",
  "tool.bb_get_assignments": "Checking assignments",
  "tool.bb_get_course_content": "Browsing course content",
  "tool.bb_get_item": "Opening the item",
  "tool.bb_get_assignment_detail": "Checking the assignment",
  "tool.bb_get_grades": "Checking grades",
  "tool.fallback_running": "Running {name}",
  "tool.evaluating_results": "Evaluating results",
  "tool.thinking": "Thinking",
  "tool.preparing_confirmation": "Preparing for confirmation",

  // -- settings/ChatsSection.tsx ---------------------------------------------------------
  "chats.ttl_off": "Off",
  "chats.ttl_1h": "1 hour",
  "chats.ttl_2h": "2 hours",
  "chats.ttl_6h": "6 hours",
  "chats.ttl_1d": "1 day",
  "chats.ttl_7d": "7 days",
  "chats.ttl_30d": "30 days",
  "chats.ttl_custom": "Custom…",
  "chats.seconds_placeholder": "seconds",
  "chats.seconds_hint": "seconds (0 = off)",
  "chats.invalid_ttl": "Invalid duration value",
  "chats.export_failed": "Could not export",
  "chats.delete_partial_failure":
    "Chats deleted from this browser. Could not delete the server-side history (backend unreachable) — try again once the backend is up.",
  "chats.delete_all_success": "All chats deleted from this browser and the server.",
  "chats.retention_title": "Chat retention period",
  "chats.retention_description":
    "Idle chats are permanently deleted from the server after this long. Pinned chats are exempt. Default: off (never deleted).",
  "chats.context_limit_title": "Model context limit",
  "chats.context_limit_description":
    "This limit trims a chat's persisted history and works independently of the retention period. Setting it to 0 disables trimming -- raising token cost and timeout risk.",
  "chats.messages_hint": "messages (0 = unlimited)",
  "chats.save": "Save",
  "chats.unsaved_changes": "You have unsaved changes",
  "chats.data_title": "Data",
  "chats.export_button": "Export all chats (JSON)",
  "chats.delete_all_button": "Delete all chats",
  "chats.delete_confirm_instruction":
    'This permanently deletes every chat, in this browser and on the server (pinned ones included), and cannot be undone. Type "{word}" to confirm.',
  "chats.deleting": "Deleting...",
  "chats.confirm_and_delete": "Confirm and delete",
  "chats.delete_confirm_word": "DELETE",
  "chats.export_filename_prefix": "rona-chats",

  // -- dashboard/StatusPanel.tsx ---------------------------------------------------------
  "status.start": "Start",
  "status.restart": "Restart",
  "status.stop": "Stop",
  "status.running_badge": "Running",
  "status.stopped_badge": "Stopped",
  "status.managed_by_systemd": "managed via systemd",
  "status.uptime": "Uptime",
  "status.model": "Model",
  "status.pro_model": "Pro model",
  "status.not_configured": "not configured",
  "status.scheduler": "Scheduler",
  "status.scheduler_running": "running",
  "status.scheduler_stopped": "stopped",
  "status.active_conversations": "Active chats",
  "status.running_agents": "Running agents",
  "status.running_tasks": "Running tasks",
  "status.database": "Database",
  "status.chat_history": "Chat history",
  "status.log_file": "Log file",
  "status.hours_minutes": "{hours}h {minutes}m",
  "status.minutes": "{minutes}m",

  // -- dashboard/ConnectionsPanel.tsx -----------------------------------------------------
  "connections.probe_failed": "Test failed",
  "connections.title": "Connections",
  "connections.probing": "Testing...",
  "connections.probe_now": "Test now",
  "connections.flash_model": "Flash model",
  "connections.pro_model": "Pro model",
  "connections.gemini_embedding": "Gemini embedding (memory)",
  "connections.checkpoint_db": "Chat history (checkpoint)",
  "connections.packages_title": "Tool packages",
  "connections.no_packages": "No optional tool packages installed. To add one:",
  "connections.missing": "missing: {fields}",
  "connections.missing_short": "missing",
  "connections.live": "live",
  "connections.error_short": "error",
  "common.continue": "Continue",
  "connections.package_id_placeholder": "package_id",
  "connections.configure": "Configure",
  "connections.close": "Close",
  "connections.config_load_failed": "Could not read the configuration",
  "connections.secret_set": "(set -- type to replace)",
  "connections.secret_unset": "(not set)",
  "connections.list_placeholder": "comma-separated",
  "connections.actions_title": "Operations",
  "connections.action_running": "Running...",
  "connections.action_continue": "Continue",

  // -- common (more) ------------------------------------------------------------------
  "common.delete": "Delete",

  // -- settings/sections.ts, SettingsRail.tsx, SettingsModal.tsx -----------------------
  "settings.section_appearance": "Appearance",
  "settings.section_chats": "Chats",
  "settings.section_status": "Status",
  "settings.section_connections": "Connections",
  "settings.section_advanced": "Advanced",
  "settings.section_tools": "Tools",
  "settings.section_tasks": "Tasks",
  "settings.section_subagents": "Agents",
  "settings.section_logs": "Logs",
  "settings.section_data": "Data",
  "settings.modal_title": "Settings",
  "settings.close": "Close",

  // -- dashboard/ConfigPanel.tsx ---------------------------------------------------------
  "config.group_general": "General",
  "config.group_model": "Model",
  "config.group_chat": "Chat",
  "config.group_subagents": "Background agents",
  "config.group_tasks": "Scheduled tasks",
  "config.group_web": "Web interface",

  // -- layout/Sidebar.tsx -----------------------------------------------------------------
  "sidebar.conversation_removed_from_folder": "Chat removed from the folder.",
  "sidebar.new_chat": "New chat",
  "sidebar.pinned_heading": "Pinned",
  "sidebar.folders_heading": "Folders",
  "sidebar.chats_heading": "Chats",
  "sidebar.new_folder": "New folder",
  "sidebar.folder_name_placeholder": "Folder name",
  "sidebar.no_chats_yet": "No chats yet.",
  "sidebar.delete_chat_title": "Delete chat",
  "sidebar.delete_chat_description": "This chat will be permanently deleted. This cannot be undone.",
  "sidebar.backend_checking": "Checking",
  "sidebar.backend_up": "Backend is up",
  "sidebar.backend_down": "Backend is down",

  // -- layout/ConversationRow.tsx -----------------------------------------------------------
  "row.pinned": "Chat pinned.",
  "row.unpinned": "Unpinned.",
  "row.pin_save_failed": "Could not save the pin to the server, reverted.",
  "row.moved_to_folder": 'Chat moved to "{folder}".',
  "row.untitled_chat": "Chat",
  "row.chat_menu": "Chat menu",
  "row.rename": "Rename",
  "row.unpin": "Unpin",
  "row.pin": "Pin",
  "row.move_to_folder": "Move to folder",
  "row.remove_from_folder": "Remove from folder",
  "row.no_folders_yet": "No folders yet.",

  // -- common (more) ------------------------------------------------------------------
  "common.loading": "Loading...",

  // -- dashboard/TasksPanel.tsx -----------------------------------------------------------
  "tasks.confirm_delete": 'Delete the task "{name}"?',
  "tasks.no_tasks": "No scheduled tasks.",
  "tasks.next_run_label": "Next run: {value}",
  "tasks.history_button": "History",
  "tasks.deactivate": "Deactivate",
  "tasks.activate": "Activate",
  "tasks.no_runs_yet": "No runs yet.",

  // -- dashboard/DataPanel.tsx -----------------------------------------------------------
  "data.tab_notes": "Notes",
  "data.tab_people": "People",
  "data.tab_memories": "Memory",
  "data.notes_not_installed": "The notes tool is not installed. To add it:",
  "data.no_notes": "No notes.",
  "data.no_people": "No people.",
  "data.no_memories": "No memories.",

  // -- layout/FolderSection.tsx -----------------------------------------------------------
  "folder.menu_label": "Folder menu",
  "folder.delete": "Delete folder",
  "folder.deleted_announcement": 'Folder "{name}" deleted, its chats moved to the unfiled list.',
  "folder.empty": "Empty folder.",

  // -- settings/RestartBanner.tsx -----------------------------------------------------------
  "restart.required_message": "The server needs to be restarted for the changes to take effect.",
  "restart.restarting": "Restarting...",
  "restart.restart_now": "Restart now",
  "restart.manual_required": "Automatic restart isn't available — restart the backend by hand (python run.py).",

  // -- hooks/useChat.ts -----------------------------------------------------------------
  "chat.approve_text": "yes, I approve",
  "chat.reject_text": "no, cancel that",

  // -- chat/Composer.tsx -----------------------------------------------------------------
  "composer.confirm_placeholder": "Do you approve? Type your reply...",
  "composer.approve": "Approve",
  "composer.reject": "Reject",
  "composer.send": "Send",

  // -- dashboard/LogsPanel.tsx -----------------------------------------------------------
  "logs.all_levels": "All levels",
  "logs.search_placeholder": "Search...",
  "logs.no_logs": "No logs yet.",

  // -- dashboard/ToolsPanel.tsx -----------------------------------------------------------
  "tools.registered_count": "{count} tools registered",
  "tools.background_badge": "background",
  "tools.requires_confirmation_badge": "needs confirmation",

  // -- chat/ProgressIndicator.tsx -----------------------------------------------------------
  "progress.duration_seconds": "{value}s",
  "progress.steps_count": "{count} steps",

  // -- common (more) ------------------------------------------------------------------
  "common.cancel": "Cancel",

  // -- api/sse.ts -----------------------------------------------------------------
  "sse.request_failed": "The request failed.",
  "sse.unknown_error": "Unknown error.",

  // -- layout/MobileTopBar.tsx -----------------------------------------------------------
  "mobile.open_chats": "Open chats",

  // -- dashboard/SubagentsPanel.tsx -----------------------------------------------------
  "subagents.no_runs": "No background agent runs.",

  // -- chat/MessageList.tsx -----------------------------------------------------------
  "messages.empty_prompt": "What's on your mind today?",

  // -- hooks/usePoll.ts -----------------------------------------------------------
  "poll.connection_error": "Connection error",

  // -- App.tsx -----------------------------------------------------------
  "app.close_sidebar": "Close sidebar",
};
