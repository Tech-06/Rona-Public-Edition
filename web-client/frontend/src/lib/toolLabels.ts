import { t, type TranslationKey } from "./i18n";
import type { ProgressEvent } from "../types";

const TOOL_LABEL_KEYS: Record<string, TranslationKey> = {
  get_time: "tool.get_time",
  web_search: "tool.web_search",
  web_scraper: "tool.web_scraper",
  get_weather: "tool.get_weather",
  translate_text: "tool.translate_text",
  get_events: "tool.get_events",
  add_event: "tool.add_event",
  edit_event: "tool.edit_event",
  delete_event: "tool.delete_event",
  get_contacts: "tool.get_contacts",
  add_contact: "tool.add_contact",
  edit_contact: "tool.edit_contact",
  delete_contact: "tool.delete_contact",
  send_email: "tool.send_email",
  get_recent_emails: "tool.get_recent_emails",
  add_note: "tool.add_note",
  get_notes: "tool.get_notes",
  edit_note: "tool.edit_note",
  delete_note: "tool.delete_note",
  add_person: "tool.add_person",
  get_people: "tool.get_people",
  edit_person: "tool.edit_person",
  delete_person: "tool.delete_person",
  search_person: "tool.search_person",
  add_memory: "tool.add_memory",
  get_memories: "tool.get_memories",
  edit_memory: "tool.edit_memory",
  delete_memory: "tool.delete_memory",
  search_memories: "tool.search_memories",
  start_subagent: "tool.start_subagent",
  list_subagents: "tool.list_subagents",
  get_subagent_report: "tool.get_subagent_report",
  dismiss_subagent_report: "tool.dismiss_subagent_report",
  create_task: "tool.create_task",
  list_tasks: "tool.list_tasks",
  get_task: "tool.get_task",
  update_task: "tool.update_task",
  delete_task: "tool.delete_task",
  get_task_run: "tool.get_task_run",
  dismiss_task_run: "tool.dismiss_task_run",
  bb_get_courses: "tool.bb_get_courses",
  bb_get_announcements: "tool.bb_get_announcements",
  bb_get_calendar: "tool.bb_get_calendar",
  bb_get_assignments: "tool.bb_get_assignments",
  bb_get_course_content: "tool.bb_get_course_content",
  bb_get_item: "tool.bb_get_item",
  bb_get_assignment_detail: "tool.bb_get_assignment_detail",
  bb_get_grades: "tool.bb_get_grades",
};

function truncate(value: string, max = 40): string {
  return value.length > max ? `${value.slice(0, max)}…` : value;
}

function detail(name: string, args?: Record<string, unknown>): string | null {
  if (!args) return null;
  if (name === "web_search" && typeof args.query === "string") {
    return truncate(args.query);
  }
  if (name === "web_scraper" && typeof args.url === "string") {
    try {
      return new URL(args.url).hostname;
    } catch {
      return truncate(args.url);
    }
  }
  if (name === "search_person" && typeof args.query === "string") {
    return truncate(args.query);
  }
  if (name === "search_memories" && typeof args.query === "string") {
    return truncate(args.query);
  }
  return null;
}

// A plain module, not a component/hook -- no render cycle of its own to
// subscribe to language changes with. Only ever called from inside a
// component that already re-renders on a locale switch (ProgressIndicator,
// MessageList), so reading the active locale at call time (via t() from
// lib/i18n, not useT()) is enough -- see LanguageProvider.tsx's own note.
export function toolLabel(name: string, args?: Record<string, unknown>): string {
  const key = TOOL_LABEL_KEYS[name];
  const base = key ? t(key) : t("tool.fallback_running", { name });
  const extra = detail(name, args);
  return extra ? `${base}: “${extra}”` : base;
}

export function agentPhaseLabel(event: ProgressEvent): string {
  if (event.hint === "followup") return t("tool.evaluating_results");
  return t("tool.thinking");
}

export function confirmPhaseLabel(): string {
  return t("tool.preparing_confirmation");
}
