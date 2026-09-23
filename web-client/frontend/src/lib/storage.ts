import { ApiError } from "../api/client";
import { dashboardApi, type ConversationExport, type HistoryFolder } from "../api/dashboard";
import { t } from "./i18n";
import type { ChatMessage, ConversationSummary, Folder } from "../types";

// Server-backed conversation storage. Every browser (and every device --
// phone, desktop, whatever origin they're connecting through) shares one
// history, held in the backend's rona.db (see backend/graph/history.py).
//
// This module keeps an in-memory cache -- indexCache/foldersCache -- that
// mirrors the server and that every read here (loadIndex/loadFolders) is
// served from synchronously, because every existing call site (Sidebar,
// FolderSection, ConversationRow, App.tsx) already calls these as plain
// synchronous functions and immediately re-renders off the result. Making
// them async would mean threading loading states through every one of
// those call sites for what's supposed to be a near-instant local read.
//
// Writes are optimistic: update the cache immediately (the caller then
// notifies subscribers, as it always has), then send the matching request
// in the background. On failure, the write reverts the cache and notifies
// again -- there's no toast channel down here, so a reverted change is the
// only signal, but the alternative (silently drifting from the server) is
// worse. syncFromServer(), run periodically by useConversationSync, is
// what reconciles everything else, including changes made on other devices.
//
// Every write goes through track(), which is what keeps a sync from
// undoing it: a sync result is only applied if no write was in flight and
// none started while the sync's own request was out -- otherwise it could
// carry the server's state from *before* the write and revert it on
// screen. A skipped sync is simply retried on the next tick.

let indexCache: ConversationSummary[] = [];
let foldersCache: Folder[] = [];
let pendingWrites = 0;
let writeGeneration = 0;

function track<T>(request: Promise<T>): Promise<T> {
  pendingWrites += 1;
  writeGeneration += 1;
  return request.finally(() => {
    pendingWrites -= 1;
  });
}

function sortIndex(index: ConversationSummary[]): ConversationSummary[] {
  return [...index].sort((a, b) => {
    if (a.pinned !== b.pinned) return a.pinned ? -1 : 1;
    return b.updatedAt - a.updatedAt;
  });
}

export function loadIndex(): ConversationSummary[] {
  return sortIndex(indexCache);
}

export function loadFolders(): Folder[] {
  return foldersCache;
}

function findConversation(conversationId: string): ConversationSummary | undefined {
  return indexCache.find((entry) => entry.conversationId === conversationId);
}

function patchConversation(
  conversationId: string,
  patch: Partial<ConversationSummary>,
): void {
  indexCache = indexCache.map((entry) =>
    entry.conversationId === conversationId ? { ...entry, ...patch } : entry,
  );
}

function fromHistoryFolder(row: HistoryFolder): Folder {
  return { id: row.id, name: row.name, createdAt: row.createdAt, collapsed: row.collapsed };
}

/** Pulls the full conversation list + folders from the server and replaces
 * the cache wholesale, then notifies subscribers. Called on startup,
 * periodically and on focus by useConversationSync, and after every turn
 * by useChat. Silently skipped (and retried next time) while a local write
 * is in flight -- see the module comment above. */
export async function syncFromServer(): Promise<void> {
  const generation = writeGeneration;
  const result = await dashboardApi.history();
  if (pendingWrites > 0 || generation !== writeGeneration) return;
  indexCache = result.conversations.map((row) => ({
    conversationId: row.conversationId,
    title: row.title || t("row.untitled_chat"),
    updatedAt: row.updatedAt,
    pinned: row.pinned,
    folderId: row.folderId,
    titleCustom: row.titleCustom,
  }));
  foldersCache = result.folders.map(fromHistoryFolder);
  notifyConversationsChanged();
}

export interface ServerConversation {
  messages: ChatMessage[];
  /** The server's last-modified stamp for this conversation -- compared
   * against the conversation list's copy (see useChat.ts) to tell whether
   * another device has added to it since it was loaded here. */
  updatedAt: number;
}

/** Fetches one conversation's full transcript, or null if the server
 * doesn't have it (yet -- a brand-new chat before its first turn lands). */
export async function fetchConversation(conversationId: string): Promise<ServerConversation | null> {
  try {
    const row = await dashboardApi.historyConversation(conversationId);
    return { messages: row.messages, updatedAt: row.updatedAt };
  } catch (err) {
    if (err instanceof ApiError && err.status === 404) return null;
    throw err;
  }
}

export function renameConversation(conversationId: string, title: string): void {
  const trimmed = title.trim();
  if (!trimmed) return;
  const previous = findConversation(conversationId);
  if (!previous) return;
  patchConversation(conversationId, { title: trimmed, titleCustom: true });
  track(dashboardApi.renameHistoryConversation(conversationId, trimmed)).catch(() => {
    patchConversation(conversationId, { title: previous.title, titleCustom: previous.titleCustom });
    notifyConversationsChanged();
  });
}

/** Optimistic like every other write here, but returns the request so
 * ConversationRow can announce how it went. Pin state lives in the
 * conversation registry (POST /api/conversations/{id}/pin -- see
 * backend/graph/conversations.py), the same place the TTL purge reads it
 * from, which is why it has to reach the server and not just this cache. */
export function setConversationPinned(conversationId: string, pinned: boolean): Promise<void> {
  const previous = findConversation(conversationId);
  patchConversation(conversationId, { pinned });
  return track(dashboardApi.setConversationPinned(conversationId, pinned)).then(
    () => undefined,
    (err: unknown) => {
      if (previous) patchConversation(conversationId, { pinned: previous.pinned });
      notifyConversationsChanged();
      throw err;
    },
  );
}

export function setConversationFolder(conversationId: string, folderId: string | null): void {
  const previous = findConversation(conversationId);
  if (!previous) return;
  patchConversation(conversationId, { folderId });
  track(dashboardApi.moveHistoryConversation(conversationId, folderId)).catch(() => {
    patchConversation(conversationId, { folderId: previous.folderId });
    notifyConversationsChanged();
  });
}

/** Removes a conversation from the local cache immediately -- the actual
 * server-side delete (DELETE /api/conversations/{id}, which also drops its
 * history row) is issued by App.tsx's removeConversation. */
export function deleteConversation(conversationId: string): void {
  indexCache = indexCache.filter((entry) => entry.conversationId !== conversationId);
  writeGeneration += 1;
}

export function createFolder(name: string): Folder {
  const trimmed = name.trim() || t("sidebar.new_folder");
  // Optimistic placeholder -- swapped for the server's real folder once the
  // request resolves. Callers (Sidebar's commitCreateFolder) don't hold on
  // to the return value across the async gap, they just notify and let the
  // next render read loadFolders() again, so the id swap is invisible.
  const placeholder: Folder = {
    id: `pending-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`,
    name: trimmed,
    createdAt: Date.now(),
    collapsed: false,
  };
  foldersCache = [...foldersCache, placeholder];
  track(dashboardApi.createHistoryFolder(trimmed))
    .then((created) => {
      const real = fromHistoryFolder(created);
      const withoutEither = foldersCache.filter(
        (folder) => folder.id !== placeholder.id && folder.id !== real.id,
      );
      foldersCache = [...withoutEither, real];
      notifyConversationsChanged();
    })
    .catch(() => {
      foldersCache = foldersCache.filter((folder) => folder.id !== placeholder.id);
      notifyConversationsChanged();
    });
  return placeholder;
}

export function renameFolder(folderId: string, name: string): void {
  const trimmed = name.trim();
  if (!trimmed) return;
  const previous = foldersCache.find((folder) => folder.id === folderId);
  if (!previous) return;
  foldersCache = foldersCache.map((folder) =>
    folder.id === folderId ? { ...folder, name: trimmed } : folder,
  );
  track(dashboardApi.renameHistoryFolder(folderId, trimmed)).catch(() => {
    foldersCache = foldersCache.map((folder) =>
      folder.id === folderId ? { ...folder, name: previous.name } : folder,
    );
    notifyConversationsChanged();
  });
}

export function setFolderCollapsed(folderId: string, collapsed: boolean): void {
  const previous = foldersCache.find((folder) => folder.id === folderId);
  if (!previous) return;
  foldersCache = foldersCache.map((folder) =>
    folder.id === folderId ? { ...folder, collapsed } : folder,
  );
  track(dashboardApi.setHistoryFolderCollapsed(folderId, collapsed)).catch(() => {
    foldersCache = foldersCache.map((folder) =>
      folder.id === folderId ? { ...folder, collapsed: previous.collapsed } : folder,
    );
    notifyConversationsChanged();
  });
}

/** Un-files every conversation in the folder (folderId -> null) instead of
 * deleting them -- deleting a folder must never delete chats. */
export function deleteFolder(folderId: string): void {
  const removedFolder = foldersCache.find((folder) => folder.id === folderId);
  const movedConversationIds = indexCache
    .filter((entry) => entry.folderId === folderId)
    .map((entry) => entry.conversationId);
  foldersCache = foldersCache.filter((folder) => folder.id !== folderId);
  indexCache = indexCache.map((entry) =>
    entry.folderId === folderId ? { ...entry, folderId: null } : entry,
  );
  track(dashboardApi.deleteHistoryFolder(folderId)).catch(() => {
    if (removedFolder) foldersCache = [...foldersCache, removedFolder];
    indexCache = indexCache.map((entry) =>
      movedConversationIds.includes(entry.conversationId) ? { ...entry, folderId } : entry,
    );
    notifyConversationsChanged();
  });
}

export async function exportAll(): Promise<ConversationExport> {
  return dashboardApi.exportHistory();
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

/** Empties the local cache. Called after the server-side "delete all"
 * request (dashboardApi.deleteAllServerConversations(), which also wipes
 * every history row and folder -- see backend/app/dashboard.py's
 * delete_all_conversations) has already completed. Also drops this
 * browser's pre-server copy (see migrateLegacyLocalHistory), which is
 * otherwise kept around untouched: "delete all" has to mean all. */
export function clearAll(): void {
  indexCache = [];
  foldersCache = [];
  writeGeneration += 1;
  removeLegacyLocalHistory();
}

// -- one-time migration from the pre-server, per-origin localStorage ----------

const LEGACY_INDEX_KEY = "rona:conversations";
const LEGACY_MESSAGES_PREFIX = "rona:messages:";
const LEGACY_FOLDERS_KEY = "rona:folders";
const MIGRATED_KEY = "rona:history-migrated";

function safeParseLegacy<T>(raw: string | null, fallback: T): T {
  if (!raw) return fallback;
  try {
    return JSON.parse(raw) as T;
  } catch {
    return fallback;
  }
}

function removeLegacyLocalHistory(): void {
  try {
    const keys: string[] = [];
    for (let i = 0; i < localStorage.length; i++) {
      const key = localStorage.key(i);
      if (
        key &&
        (key === LEGACY_INDEX_KEY || key === LEGACY_FOLDERS_KEY || key.startsWith(LEGACY_MESSAGES_PREFIX))
      ) {
        keys.push(key);
      }
    }
    for (const key of keys) localStorage.removeItem(key);
  } catch {
    // storage unavailable - nothing to remove
  }
}

/** One-time migration for a browser that still has the old (pre-server)
 * per-origin localStorage history: uploads it to the server via
 * POST /api/history/import, which merges it with whatever the server
 * already has (see graph.history.import_conversations) -- so turns that
 * only this browser saw, folders and renames made in the old UI all end
 * up in the shared history, on every device.
 *
 * Runs once per browser (per origin): a marker is set only after the
 * server confirmed the import, so a failed attempt is retried on the next
 * start. The marker is also what stops a conversation deleted on another
 * device from being resurrected by this browser's old copy later. The old
 * copy itself is left in place, untouched and never read again, rather
 * than deleted by an automatic process -- clearAll() ("delete all") is
 * the one thing that removes it. */
export async function migrateLegacyLocalHistory(): Promise<void> {
  let rawIndex: string | null;
  let alreadyMigrated: boolean;
  try {
    rawIndex = localStorage.getItem(LEGACY_INDEX_KEY);
    alreadyMigrated = localStorage.getItem(MIGRATED_KEY) !== null;
  } catch {
    return;
  }
  if (alreadyMigrated) return;

  type LegacyConversation = Partial<ConversationSummary> & { conversationId?: string };
  const legacyIndex = safeParseLegacy<LegacyConversation[]>(rawIndex, []);
  const legacyFolders = safeParseLegacy<Folder[]>(localStorage.getItem(LEGACY_FOLDERS_KEY), []);

  if (legacyIndex.length > 0 || legacyFolders.length > 0) {
    const conversations = legacyIndex
      .filter((entry): entry is LegacyConversation & { conversationId: string } =>
        Boolean(entry?.conversationId),
      )
      .map((entry) => ({
        conversationId: entry.conversationId,
        title: entry.title ?? "",
        titleCustom: entry.titleCustom ?? false,
        updatedAt: entry.updatedAt ?? Date.now(),
        pinned: entry.pinned ?? false,
        folderId: entry.folderId ?? null,
        messages: safeParseLegacy<ChatMessage[]>(
          localStorage.getItem(LEGACY_MESSAGES_PREFIX + entry.conversationId),
          [],
        ),
      }));
    // Throws on failure (backend unreachable, ...) -- the marker below is
    // then never set, so the next start tries again.
    await dashboardApi.importHistory({ conversations, folders: legacyFolders });
  }

  try {
    localStorage.setItem(MIGRATED_KEY, new Date().toISOString());
  } catch {
    // storage unavailable: the import is idempotent server-side, so
    // repeating it next time is harmless
  }
}
