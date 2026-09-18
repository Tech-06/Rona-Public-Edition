import { api } from "./client";

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

export interface GoogleAccountInfo {
  account: string;
  token_present: boolean;
  calendar: boolean;
  contacts: boolean;
  mail: boolean;
}

export interface ConnectionsResponse {
  google_accounts: GoogleAccountInfo[];
  google_credentials_file_present: boolean;
  tavily_configured: boolean;
  deepl_configured: boolean;
  openweather_configured: boolean;
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
  google: Record<string, ProbeResult>;
  weather: ProbeResult;
  translate: ProbeResult;
  web_search: ProbeResult;
  llm: ProbeResult;
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

export interface ServerConversationSummary {
  conversation_id: string;
  last_active: string;
  last_active_seconds_ago: number;
  pinned: boolean;
}

export interface ServerConversationsResponse {
  conversations: ServerConversationSummary[];
  purged: string[];
  ttl_seconds: number;
  max_history_messages: number;
}

export interface ConversationPinResponse {
  thread_id: string;
  last_active: string;
  pinned: boolean;
  purged_at: string | null;
}

export const dashboardApi = {
  status: () => api.get<StatusResponse>("/api/status"),
  connections: () => api.get<ConnectionsResponse>("/api/connections"),
  probeConnections: () => api.post<ProbeResponse>("/api/connections/probe"),
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
  notes: () => api.get<{ success: boolean; notes: Array<Record<string, unknown>> }>("/api/data/notes"),
  people: () => api.get<{ success: boolean; people: Array<Record<string, unknown>> }>("/api/data/people"),
  memories: () =>
    api.get<{ success: boolean; memories: Array<Record<string, unknown>> }>(
      "/api/data/memories?person=all",
    ),
  serverStatus: () => api.get<ServerStatusResponse>("/host/server"),
  serverAction: (action: "start" | "stop" | "restart") =>
    api.post<{ ok: boolean; detail: string }>(`/host/server/${action}`),
  serverConversations: () => api.get<ServerConversationsResponse>("/api/conversations"),
  setConversationPinned: (conversationId: string, pinned: boolean) =>
    api.post<ConversationPinResponse>(`/api/conversations/${conversationId}/pin`, { pinned }),
  deleteServerConversation: (conversationId: string) =>
    api.del<{ deleted: boolean }>(`/api/conversations/${conversationId}`),
  deleteAllServerConversations: () =>
    api.del<{ deleted: number; skipped: number }>("/api/conversations"),
};
