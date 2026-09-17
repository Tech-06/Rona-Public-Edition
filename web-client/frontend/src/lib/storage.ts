import type { ChatMessage, ConversationSummary } from "../types";

const INDEX_KEY = "rona:conversations";
const MESSAGES_PREFIX = "rona:messages:";
const MAX_CONVERSATIONS = 30;

function safeParse<T>(raw: string | null, fallback: T): T {
  if (!raw) return fallback;
  try {
    return JSON.parse(raw) as T;
  } catch {
    return fallback;
  }
}

export function loadIndex(): ConversationSummary[] {
  try {
    return safeParse<ConversationSummary[]>(localStorage.getItem(INDEX_KEY), []);
  } catch {
    return [];
  }
}

export function loadMessages(conversationId: string): ChatMessage[] {
  try {
    return safeParse<ChatMessage[]>(
      localStorage.getItem(MESSAGES_PREFIX + conversationId),
      [],
    );
  } catch {
    return [];
  }
}

export function saveConversation(
  conversationId: string,
  title: string,
  messages: ChatMessage[],
): void {
  try {
    localStorage.setItem(MESSAGES_PREFIX + conversationId, JSON.stringify(messages));
    const index = loadIndex().filter((entry) => entry.conversationId !== conversationId);
    index.unshift({ conversationId, title, updatedAt: Date.now() });
    localStorage.setItem(INDEX_KEY, JSON.stringify(index.slice(0, MAX_CONVERSATIONS)));
  } catch {
    // storage unavailable (private mode, quota) - conversation stays in memory only
  }
}

export function deleteConversation(conversationId: string): void {
  try {
    localStorage.removeItem(MESSAGES_PREFIX + conversationId);
    const index = loadIndex().filter((entry) => entry.conversationId !== conversationId);
    localStorage.setItem(INDEX_KEY, JSON.stringify(index));
  } catch {
    // ignore
  }
}
