export type ChatStatus = "ok" | "confirmation_required";

export interface ToolCallInfo {
  name: string;
  args: Record<string, unknown>;
}

export interface ChatResult {
  status: ChatStatus;
  reply: string;
  tool_calls: ToolCallInfo[] | null;
  conversation_id: string;
}

export type ProgressEventType =
  | "agent_start"
  | "tool_start"
  | "tool_end"
  | "confirm_start";

export interface ProgressEvent {
  type: ProgressEventType;
  hint?: "first" | "followup";
  call_id?: string;
  name?: string;
  args?: Record<string, unknown>;
  status?: "ok" | "error" | "rejected" | "unknown_tool" | "bad_args";
  duration_ms?: number;
  names?: string[];
}

export interface StepRecord {
  callId: string;
  name: string;
  args: Record<string, unknown>;
  status: "running" | "ok" | "error" | "rejected" | "unknown_tool" | "bad_args";
  durationMs: number | null;
}

export type MessageRole = "user" | "assistant";

export interface ChatMessage {
  id: string;
  role: MessageRole;
  content: string;
  createdAt: number;
  pending?: boolean;
  awaitingConfirmation?: boolean;
  toolCalls?: ToolCallInfo[] | null;
  steps?: StepRecord[];
  totalDurationMs?: number;
  error?: string;
}

export interface ConversationSummary {
  conversationId: string;
  title: string;
  updatedAt: number;
  pinned: boolean;
  folderId: string | null;
  /** True once the user has explicitly renamed this conversation, so
   * saveConversation() stops overwriting the title with the auto-derived
   * first-message snippet on every turn. */
  titleCustom: boolean;
}

export interface Folder {
  id: string;
  name: string;
  createdAt: number;
  collapsed: boolean;
}

export type SettingsSectionId =
  | "appearance"
  | "chats"
  | "status"
  | "connections"
  | "advanced"
  | "tools"
  | "tasks"
  | "subagents"
  | "logs"
  | "data";
