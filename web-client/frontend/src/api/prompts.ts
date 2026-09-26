import { api } from "./client";

// Wire shapes for the prompt-editing API (backend/app/prompt_store.py +
// prompts_api.py). Exactly 9
// prompt ids are ever returned -- 7 "main" prompts loaded into every chat
// turn, plus one background-worker prompt each for subagents and
// scheduled tasks.

export type PromptGroup = "main" | "subagent" | "trigger";

/** A `{{NAME}}` placeholder available for insertion, with its current
 * resolved value (for the active backend language) shown as a hint. */
export interface PromptPlaceholder {
  name: string;
  value: string;
}

export interface PromptSummary {
  id: string;
  filename: string;
  group: PromptGroup;
  customized: boolean;
  /** null when unknown (e.g. no override exists yet, so there is nothing
   * to compare the tracked default hash against). */
  default_changed: boolean | null;
  updated_at: string | null;
  size_bytes: number;
  required_placeholders: string[];
  required_nonempty: boolean;
}

export interface PromptDetail extends PromptSummary {
  content: string;
  default_content: string;
  /** First 16 hex chars of the effective raw content's sha256; sent back
   * as `base_version` on save so the server can detect a concurrent edit. */
  version: string;
  default_version: string;
}

export interface PromptListResponse {
  prompts: PromptSummary[];
  placeholders: PromptPlaceholder[];
  max_bytes: number;
}

export interface PromptSaveResponse extends PromptDetail {
  warnings: string[];
}

export const promptsApi = {
  list: () => api.get<PromptListResponse>("/api/prompts"),
  get: (id: string) => api.get<PromptDetail>(`/api/prompts/${id}`),
  save: (id: string, content: string, baseVersion: string) =>
    api.put<PromptSaveResponse>(`/api/prompts/${id}`, { content, base_version: baseVersion }),
  reset: (id: string) => api.del<PromptDetail>(`/api/prompts/${id}`),
};
