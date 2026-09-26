import { api } from "./client";
import type { ChatMessage } from "../types";

export interface StatusResponse {
  app: string;
  uptime_seconds: number;
  flash_model: string;
  pro_configured: boolean;
  scheduler_running: boolean;
  active_conversations: number;
  running_subagents: number;
  running_trigger_occurrences: number;
  db_size_bytes: number | null;
  checkpoint_db_size_bytes: number | null;
  log_size_bytes: number | null;
}

/** One user-configurable value a package declares. Metadata only -- a
 * secret's value is never sent to the browser, only whether one is set. */
export interface PackageConfigField {
  key: string;
  label: string;
  description: string;
  type: "string" | "integer" | "boolean" | "list";
  target: "env" | "config" | "file";
  secret: boolean;
  required: boolean;
  set: boolean;
  /** Present only on the per-package config endpoint, and null for secrets. */
  value?: unknown;
}

/** An operator-facing operation the package exposes (authorizing an account,
 * revoking one, ...). Actions marked cli_only never reach the dashboard. */
export interface PackageAction {
  id: string;
  label: string;
  description: string;
  destructive: boolean;
  cli_only: boolean;
  params: PackageConfigField[];
}

export interface PackageStatus {
  id: string;
  name: string;
  version: string;
  kind: "tool" | "library";
  description: string;
  provides: string[];
  requires: string[];
  configured: boolean;
  missing_config: string[];
  config_fields: PackageConfigField[];
  actions: PackageAction[];
  /** Installed package ids that list this one in their own `requires` --
   * shown when trying to uninstall it, since doing so would break them. */
  dependents: string[];
  /** Human-readable `requires` violations against what's actually
   * installed (missing dependency, or an installed version too old). */
  requirement_problems: string[];
}

export interface PackageConfigResponse {
  id: string;
  fields: PackageConfigField[];
}

export interface PackageConfigUpdateResponse {
  ok: boolean;
  health: ProbeResult;
  restart_required: boolean;
}

/** One step of an action. `input_required` means the handler needs more from
 * the user: render `fields`, then post again with those values and `state`
 * handed back exactly as received. */
export interface PackageActionResponse {
  status: "ok" | "error" | "input_required";
  message: string;
  data: Record<string, unknown>;
  fields: PackageConfigField[];
  state: Record<string, unknown> | null;
}

export interface ConnectionsResponse {
  packages: PackageStatus[];
  gemini_embedding_configured: boolean;
  flash_configured: boolean;
  pro_configured: boolean;
  db_present: boolean;
  checkpoint_db_present: boolean;
}

export interface ProbeResult {
  ok: boolean;
  detail: string;
}

export interface ProbeResponse {
  packages: Record<string, ProbeResult>;
  llm: ProbeResult;
}

export interface PackagesResponse {
  packages: PackageStatus[];
  warnings: string[];
}

export interface PackageReloadResponse extends PackagesResponse {
  purged_modules: number;
}

export interface ToolSpecResponse {
  name: string;
  description: string;
  module: string;
  function: string;
  parameters: Record<string, unknown>;
  requires_confirmation: boolean | Record<string, unknown>;
  background: boolean;
}

export interface ConfigResponse {
  values: Record<string, unknown>;
  editable: string[];
}

export interface TaskResponse {
  id: string;
  name: string;
  description: string;
  status: string;
  is_recurring: boolean;
  model: string;
  cron_expression: string | null;
  scheduled_at: string | null;
  timezone: string;
  tool_name: string | null;
  max_retries: number;
  created_at: string;
  updated_at: string | null;
  next_run: string | null;
}

export interface TaskRunResponse {
  id: string;
  task_id: string;
  status: string;
  attempt: number;
  summary: string | null;
  report: string | null;
  error: string | null;
  started_at: string;
  finished_at: string | null;
}

export interface SubagentRunResponse {
  id: string;
  task: string;
  tier: string;
  status: string;
  summary: string | null;
  report: string | null;
  error: string | null;
  created_at: string;
  finished_at: string | null;
}

export interface ServerStatusResponse {
  backend_up: boolean;
  backend_detail: unknown;
  tracked_process_alive: boolean;
  tracked_pid: number | null;
  systemctl_available: boolean;
  recent_log_lines: string[];
}

export interface ConversationPinResponse {
  thread_id: string;
  last_active: string;
  pinned: boolean;
  purged_at: string | null;
}

// -- memory / archive (backend/memory/) -----------------------------------

export type MemoryLayer = "deep" | "seasonal" | "short";

export interface MemoryRecord {
  id: number;
  person_id: number | null;
  layer: MemoryLayer;
  content: string;
  created_at: string;
  metadata: Record<string, unknown>;
  access_count: number;
  layer_hits: number;
  layer_since: string;
  last_accessed: string | null;
}

export type ArchiveReason = "auto" | "manual" | "person_deleted";

export interface ArchivedMemory {
  id: number;
  memory_id: number;
  person_id: number | null;
  layer: MemoryLayer;
  content: string;
  access_count: number;
  created_at: string;
  last_accessed: string | null;
  metadata: Record<string, unknown>;
  archived_at: string;
  reason: ArchiveReason;
}

// -- server-side chat history (backend/graph/history.py) -----------------
//
// Every field here is camelCase, matching the frontend's own
// ConversationSummary/Folder/ChatMessage shapes directly (see
// web-client/frontend/src/types.ts) rather than this project's usual
// snake_case API convention: these endpoints exist specifically to be this
// web client's storage backend, so the wire shape IS the frontend shape.

export interface HistoryConversationSummary {
  conversationId: string;
  title: string;
  titleCustom: boolean;
  updatedAt: number;
  pinned: boolean;
  folderId: string | null;
}

export interface HistoryFolder {
  id: string;
  name: string;
  createdAt: number;
  collapsed: boolean;
}

export interface HistoryResponse {
  conversations: HistoryConversationSummary[];
  folders: HistoryFolder[];
}

export interface HistoryConversationDetail extends HistoryConversationSummary {
  messages: ChatMessage[];
}

/** Same shape the old client-side exportAll() used to produce (see
 * lib/storage.ts's history), now filled in server-side by
 * GET /api/history/export. */
export interface ConversationExport {
  exportedAt: string;
  conversations: Array<{
    conversationId: string;
    title: string;
    updatedAt: number;
    pinned: boolean;
    folderId: string | null;
    messages: ChatMessage[];
  }>;
}

/** Payload for the one-time localStorage -> server migration
 * (see lib/storage.ts's migrateLegacyLocalHistory()). */
export interface HistoryImportPayload {
  conversations: Array<{
    conversationId: string;
    title: string;
    titleCustom: boolean;
    updatedAt: number;
    pinned: boolean;
    folderId: string | null;
    messages: ChatMessage[];
  }>;
  folders: HistoryFolder[];
}

export interface HistoryImportResult {
  conversationsImported: number;
  conversationsMerged: number;
  foldersImported: number;
}

export const dashboardApi = {
  status: () => api.get<StatusResponse>("/api/status"),
  connections: () => api.get<ConnectionsResponse>("/api/connections"),
  probeConnections: () => api.post<ProbeResponse>("/api/connections/probe"),
  packages: () => api.get<PackagesResponse>("/api/packages"),
  /** Hot-reloads custom packages in the backend after a web-driven
   * install/update/uninstall job finishes (POST /api/packages/reload).
   * A plain `api.post` call, unlike the /host/packages/* job
   * endpoints -- this one goes through the backend, so it can 502/503/504
   * while `RELOAD=true` restarts the backend process mid-install. */
  reloadPackages: () => api.post<PackageReloadResponse>("/api/packages/reload"),
  packageConfig: (id: string) => api.get<PackageConfigResponse>(`/api/packages/${id}/config`),
  updatePackageConfig: (id: string, values: Record<string, unknown>) =>
    api.put<PackageConfigUpdateResponse>(`/api/packages/${id}/config`, values),
  runPackageAction: (
    id: string,
    actionId: string,
    params: Record<string, unknown>,
    state: Record<string, unknown> | null,
  ) =>
    api.post<PackageActionResponse>(`/api/packages/${id}/actions/${actionId}`, {
      params,
      state,
    }),
  tools: () => api.get<{ tools: ToolSpecResponse[] }>("/api/tools"),
  config: () => api.get<ConfigResponse>("/api/config"),
  updateConfig: (values: Record<string, unknown>) =>
    api.put<{ restart_required: boolean }>("/api/config", values),
  tasks: () => api.get<{ tasks: TaskResponse[] }>("/api/tasks"),
  taskRuns: (taskId: string) => api.get<{ runs: TaskRunResponse[] }>(`/api/tasks/${taskId}/runs`),
  setTaskStatus: (taskId: string, status: string) =>
    api.post<TaskResponse>(`/api/tasks/${taskId}/status`, { status }),
  deleteTask: (taskId: string) => api.del<{ deleted: boolean }>(`/api/tasks/${taskId}`),
  subagents: () => api.get<{ runs: SubagentRunResponse[] }>("/api/subagents"),
  notes: () =>
    api.get<{ success: boolean; installed: boolean; notes: Array<Record<string, unknown>> }>(
      "/api/data/notes",
    ),
  people: () => api.get<{ success: boolean; people: Array<Record<string, unknown>> }>("/api/data/people"),
  memories: () =>
    api.get<{ success: boolean; memories: MemoryRecord[]; total: number }>(
      "/api/data/memories?person=all",
    ),
  deleteMemory: (id: number) =>
    api.del<{ success: boolean; message: string }>(`/api/data/memories/${id}`),
  archiveMemory: (id: number) =>
    api.post<{ success: boolean; archive_id: number }>(`/api/data/memories/${id}/archive`),
  archive: () =>
    api.get<{ success: boolean; archive: ArchivedMemory[]; total: number }>("/api/data/archive"),
  restoreArchived: (id: number) =>
    api.post<{ success: boolean; memory_id: number }>(`/api/data/archive/${id}/restore`),
  deleteArchived: (id: number) => api.del<{ success: boolean }>(`/api/data/archive/${id}`),
  deleteNote: (id: number) => api.del<{ success: boolean }>(`/api/data/notes/${id}`),
  deletePerson: (id: number) =>
    api.del<{ success: boolean; archived_memories: number }>(`/api/data/people/${id}`),
  serverStatus: () => api.get<ServerStatusResponse>("/host/server"),
  serverAction: (action: "start" | "stop" | "restart") =>
    api.post<{ ok: boolean; detail: string }>(`/host/server/${action}`),
  setConversationPinned: (conversationId: string, pinned: boolean) =>
    api.post<ConversationPinResponse>(`/api/conversations/${conversationId}/pin`, { pinned }),
  deleteServerConversation: (conversationId: string) =>
    api.del<{ deleted: boolean }>(`/api/conversations/${conversationId}`),
  deleteAllServerConversations: () =>
    api.del<{ deleted: number; skipped: number }>("/api/conversations"),
  history: () => api.get<HistoryResponse>("/api/history"),
  historyConversation: (conversationId: string) =>
    api.get<HistoryConversationDetail>(`/api/history/${conversationId}`),
  renameHistoryConversation: (conversationId: string, title: string) =>
    api.patch<HistoryConversationSummary>(`/api/history/${conversationId}`, { title }),
  moveHistoryConversation: (conversationId: string, folderId: string | null) =>
    api.patch<HistoryConversationSummary>(`/api/history/${conversationId}`, { folderId }),
  exportHistory: () => api.get<ConversationExport>("/api/history/export"),
  importHistory: (payload: HistoryImportPayload) =>
    api.post<HistoryImportResult>("/api/history/import", payload),
  createHistoryFolder: (name: string) => api.post<HistoryFolder>("/api/history/folders", { name }),
  renameHistoryFolder: (folderId: string, name: string) =>
    api.patch<HistoryFolder>(`/api/history/folders/${folderId}`, { name }),
  setHistoryFolderCollapsed: (folderId: string, collapsed: boolean) =>
    api.patch<HistoryFolder>(`/api/history/folders/${folderId}`, { collapsed }),
  deleteHistoryFolder: (folderId: string) =>
    api.del<{ deleted: boolean }>(`/api/history/folders/${folderId}`),
};
