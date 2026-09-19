import { t } from "./i18n";
import type { ChatMessage, ConversationSummary, Folder } from "../types";

const INDEX_KEY = "rona:conversations";
const MESSAGES_PREFIX = "rona:messages:";
const FOLDERS_KEY = "rona:folders";

// Budget for UNPINNED conversations specifically, not "30 minus however
// many are pinned" -- with the subtraction form, enough pinned chats would
// drive the budget to zero and evict the very conversation being saved.
const MAX_UNPINNED = 30;

function safeParse<T>(raw: string | null, fallback: T): T {
  if (!raw) return fallback;
  try {
    return JSON.parse(raw) as T;
  } catch {
    return fallback;
  }
}

type StoredConversation = Partial<ConversationSummary> & { conversationId: string };

function normalize(entry: StoredConversation): ConversationSummary {
  return {
    conversationId: entry.conversationId,
    title: entry.title ?? t("row.untitled_chat"),
    updatedAt: entry.updatedAt ?? Date.now(),
    pinned: entry.pinned ?? false,
    folderId: entry.folderId ?? null,
    titleCustom: entry.titleCustom ?? false,
  };
}

function sortIndex(index: ConversationSummary[]): ConversationSummary[] {
  return [...index].sort((a, b) => {
    if (a.pinned !== b.pinned) return a.pinned ? -1 : 1;
    return b.updatedAt - a.updatedAt;
  });
}

export function loadIndex(): ConversationSummary[] {
  try {
    const raw = safeParse<StoredConversation[]>(localStorage.getItem(INDEX_KEY), []);
    return sortIndex(raw.filter((entry) => !!entry?.conversationId).map(normalize));
  } catch {
    return [];
  }
}

function writeIndex(index: ConversationSummary[]): void {
  localStorage.setItem(INDEX_KEY, JSON.stringify(index));
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
  fallbackTitle: string,
  messages: ChatMessage[],
): void {
  try {
    localStorage.setItem(MESSAGES_PREFIX + conversationId, JSON.stringify(messages));

    const index = loadIndex();
    const existing = index.find((entry) => entry.conversationId === conversationId);
    const entry = normalize({
      conversationId,
      // Once the user has renamed a conversation, later turns must not
      // clobber that title back to the auto-derived first-message snippet.
      title: existing?.titleCustom ? existing.title : fallbackTitle,
      updatedAt: Date.now(),
      pinned: existing?.pinned,
      folderId: existing?.folderId,
      titleCustom: existing?.titleCustom,
    });
    const rest = index.filter((e) => e.conversationId !== conversationId);
    const next = [entry, ...rest];

    const pinned = next.filter((e) => e.pinned);
    const unpinned = next.filter((e) => !e.pinned);
    const kept = unpinned.slice(0, MAX_UNPINNED);
    const evicted = unpinned.slice(MAX_UNPINNED);
    for (const e of evicted) {
      localStorage.removeItem(MESSAGES_PREFIX + e.conversationId);
    }
    writeIndex([...pinned, ...kept]);
  } catch {
    // storage unavailable (private mode, quota) - conversation stays in memory only
  }
}

export function deleteConversation(conversationId: string): void {
  try {
    localStorage.removeItem(MESSAGES_PREFIX + conversationId);
    writeIndex(loadIndex().filter((entry) => entry.conversationId !== conversationId));
  } catch {
    // ignore
  }
}

export function renameConversation(conversationId: string, title: string): void {
  const trimmed = title.trim();
  if (!trimmed) return;
  try {
    writeIndex(
      loadIndex().map((entry) =>
        entry.conversationId === conversationId
          ? { ...entry, title: trimmed, titleCustom: true }
          : entry,
      ),
    );
  } catch {
    // ignore
  }
}

export function setConversationPinned(conversationId: string, pinned: boolean): void {
  try {
    writeIndex(
      loadIndex().map((entry) =>
        entry.conversationId === conversationId ? { ...entry, pinned } : entry,
      ),
    );
  } catch {
    // ignore
  }
}

export function setConversationFolder(conversationId: string, folderId: string | null): void {
  try {
    writeIndex(
      loadIndex().map((entry) =>
        entry.conversationId === conversationId ? { ...entry, folderId } : entry,
      ),
    );
  } catch {
    // ignore
  }
}

/** Deletes local conversations the backend says it purged (TTL expiry).
 * Only ever call this with ids from the server's `purged` list -- never
 * infer deletion from a conversation being merely absent from the
 * server's active list, since absence there can just mean "not synced
 * yet" (fresh rona.db, restart before reconcile, ...) and wiping on that
 * basis would destroy the user's only copy of the transcript. */
export function removePurgedConversations(purgedIds: string[]): void {
  if (purgedIds.length === 0) return;
  try {
    const purged = new Set(purgedIds);
    const index = loadIndex();
    const next = index.filter((entry) => !purged.has(entry.conversationId));
    if (next.length === index.length) return;
    for (const entry of index) {
      if (purged.has(entry.conversationId)) {
        localStorage.removeItem(MESSAGES_PREFIX + entry.conversationId);
      }
    }
    writeIndex(next);
  } catch {
    // ignore
  }
}

export function loadFolders(): Folder[] {
  try {
    return safeParse<Folder[]>(localStorage.getItem(FOLDERS_KEY), []);
  } catch {
    return [];
  }
}

function writeFolders(folders: Folder[]): void {
  localStorage.setItem(FOLDERS_KEY, JSON.stringify(folders));
}

export function createFolder(name: string): Folder {
  const folder: Folder = {
    id: `folder-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`,
    name: name.trim() || t("sidebar.new_folder"),
    createdAt: Date.now(),
    collapsed: false,
  };
  try {
    writeFolders([...loadFolders(), folder]);
  } catch {
    // ignore - folder still returned so the caller can hold it in memory
  }
  return folder;
}

export function renameFolder(folderId: string, name: string): void {
  const trimmed = name.trim();
  if (!trimmed) return;
  try {
    writeFolders(
      loadFolders().map((folder) => (folder.id === folderId ? { ...folder, name: trimmed } : folder)),
    );
  } catch {
    // ignore
  }
}

export function setFolderCollapsed(folderId: string, collapsed: boolean): void {
  try {
    writeFolders(
      loadFolders().map((folder) => (folder.id === folderId ? { ...folder, collapsed } : folder)),
    );
  } catch {
    // ignore
  }
}

/** Un-files every conversation in the folder (folderId -> null) instead of
 * deleting them -- deleting a folder must never delete chats. */
export function deleteFolder(folderId: string): void {
  try {
    writeFolders(loadFolders().filter((folder) => folder.id !== folderId));
    writeIndex(
      loadIndex().map((entry) =>
        entry.folderId === folderId ? { ...entry, folderId: null } : entry,
      ),
    );
  } catch {
    // ignore
  }
}

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

export function exportAll(): ConversationExport {
  const index = loadIndex();
  return {
    exportedAt: new Date().toISOString(),
    conversations: index.map((entry) => ({
      conversationId: entry.conversationId,
      title: entry.title,
      updatedAt: entry.updatedAt,
      pinned: entry.pinned,
      folderId: entry.folderId,
      messages: loadMessages(entry.conversationId),
    })),
  };
}

const CONVERSATIONS_CHANGED_EVENT = "rona:conversations-changed";

/** Code that mutates the conversation index from outside App's own
 * callback props (e.g. the settings modal's "delete all") dispatches this
 * so App can refresh its in-memory list without prop-drilling a refresh
 * callback all the way through the settings tree. */
export function notifyConversationsChanged(): void {
  window.dispatchEvent(new Event(CONVERSATIONS_CHANGED_EVENT));
}

export function onConversationsChanged(handler: () => void): () => void {
  window.addEventListener(CONVERSATIONS_CHANGED_EVENT, handler);
  return () => window.removeEventListener(CONVERSATIONS_CHANGED_EVENT, handler);
}

/** Removes every local conversation, its messages (including any orphaned
 * blobs left behind by the old, pre-fix eviction path), and every folder.
 * This is the settings "delete all conversations" data control -- an
 * explicit, confirmed nuke, unlike removePurgedConversations. */
export function clearAll(): void {
  try {
    const keysToRemove: string[] = [];
    for (let i = 0; i < localStorage.length; i++) {
      const key = localStorage.key(i);
      if (key && (key === INDEX_KEY || key === FOLDERS_KEY || key.startsWith(MESSAGES_PREFIX))) {
        keysToRemove.push(key);
      }
    }
    for (const key of keysToRemove) localStorage.removeItem(key);
  } catch {
    // ignore
  }
}
