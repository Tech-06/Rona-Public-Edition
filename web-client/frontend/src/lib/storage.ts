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
// Writes follow the same optimistic pattern the old localStorage version
// used to (mutate synchronously, notify, and only "await" is done by the
// network request that follows in the background): update the cache and
// notify subscribers immediately, then fire the matching PATCH/POST/DELETE
// request. On failure, the mutation reverts the cache and notifies again
// -- there's no toast channel down here, so a reverted change is the only
// signal, but the alternative (silently drifting from the server forever)
// is worse. `syncFromServer()` (called periodically by
// useConversationSync) is what eventually reconciles anything a revert
// missed, e.g. a request that failed after the response was already lost.
//
// `pendingWrites` guards against the reverse race: a periodic sync landing
// while an optimistic write is still in flight would otherwise overwrite
// the optimistic value with the pre-write server state.

let indexCache: ConversationSummary[] = [];
let foldersCache: Folder[] = [];
let pendingWrites = 0;

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
 * the cache wholesale. Called on startup and periodically/on focus by
 * useConversationSync. Skipped (silently, tried again next tick) while an
 * optimistic write is in flight -- see the module docstring above. */
export async function syncFromServer(): Promise<void> {
  const result = await dashboardApi.history();
  if (pendingWrites > 0) return;
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

/** Fetches one conversation's full transcript. There is no local message
 * cache anymore (see useChat.ts) -- every open of a conversation re-reads
 * it from the server, which is also how a turn that finished while this
 * client was backgrounded/disconnected becomes visible. */
export async function fetchMessages(conversationId: string): Promise<ChatMessage[]> {
  try {
    const row = await dashboardApi.historyConversation(conversationId);
    return row.messages;
  } catch (err) {
    if (err instanceof ApiError && err.status === 404) return [];
    throw err;
  }
}

export function renameConversation(conversationId: string, title: string): void {
  const trimmed = title.trim();
  if (!trimmed) return;
  const previous = findConversation(conversationId);
  if (!previous) return;
  patchConversation(conversationId, { title: trimmed, titleCustom: true });
  pendingWrites += 1;
  dashboardApi
    .renameHistoryConversation(conversationId, trimmed)
    .catch(() => {
      patchConversation(conversationId, { title: previous.title, titleCustom: previous.titleCustom });
      notifyConversationsChanged();
    })
    .finally(() => {
      pendingWrites -= 1;
    });
}

/** Local-only: no network call of its own. ConversationRow's pin toggle
 * already POSTs to /api/conversations/{id}/pin itself (see its own
 * try/catch + revert there) -- that endpoint is the pin/TTL source of
 * truth (backend/graph/conversations.py), so this just keeps the cache
 * that loadIndex() reads from in sync with what the caller just decided. */
export function setConversationPinned(conversationId: string, pinned: boolean): void {
  patchConversation(conversationId, { pinned });
}

export function setConversationFolder(conversationId: string, folderId: string | null): void {
  const previous = findConversation(conversationId);
  if (!previous) return;
  patchConversation(conversationId, { folderId });
  pendingWrites += 1;
  dashboardApi
    .moveHistoryConversation(conversationId, folderId)
    .catch(() => {
      patchConversation(conversationId, { folderId: previous.folderId });
      notifyConversationsChanged();
    })
    .finally(() => {
      pendingWrites -= 1;
    });
}

/** Removes a conversation from the local cache immediately -- the actual
 * server-side delete (DELETE /api/conversations/{id}, which also drops its
 * history row) is issued by App.tsx's removeConversation, same as before. */
export function deleteConversation(conversationId: string): void {
  indexCache = indexCache.filter((entry) => entry.conversationId !== conversationId);
}

export function createFolder(name: string): Folder {
  const trimmed = name.trim() || t("sidebar.new_folder");
  // Optimistic placeholder id -- replaced by the server's real id once the
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
  dashboardApi
    .createHistoryFolder(trimmed)
    .then((created) => {
      foldersCache = foldersCache.map((folder) =>
        folder.id === placeholder.id ? fromHistoryFolder(created) : folder,
      );
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
  dashboardApi.renameHistoryFolder(folderId, trimmed).catch(() => {
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
  dashboardApi.setHistoryFolderCollapsed(folderId, collapsed).catch(() => {
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
  dashboardApi.deleteHistoryFolder(folderId).catch(() => {
    if (removedFolder) foldersCache = [...foldersCache, removedFolder];
    indexCache = indexCache.map((entry) =>
      movedConversationIds.includes(entry.conversationId)
        ? { ...entry, folderId }
        : entry,
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
 * delete_all_conversations) has already completed; this just brings the
 * cache in line with what the server now has. */
export function clearAll(): void {
  indexCache = [];
  foldersCache = [];
}

// -- one-time migration from the pre-server, per-origin localStorage ----------

const LEGACY_INDEX_KEY = "rona:conversations";
const LEGACY_MESSAGES_PREFIX = "rona:messages:";
const LEGACY_FOLDERS_KEY = "rona:folders";

function safeParseLegacy<T>(raw: string | null, fallback: T): T {
  if (!raw) return fallback;
  try {
    return JSON.parse(raw) as T;
  } catch {
    return fallback;
  }
}

/** One-time migration for a browser that still has the old (pre-server)
 * per-origin localStorage history: uploads it to the server via
 * POST /api/history/import, then deletes the local copy so it's never
 * read (or re-imported) again. Safe to call on every startup -- a no-op
 * once the legacy keys are gone, and importing the same export twice from
 * two different devices is a harmless no-op server-side too (see
 * graph.history.import_conversations's docstring).
 *
 * This is what lets a phone and a desktop that each had their own
 * localStorage history end up sharing one list after both have opened the
 * app once post-upgrade -- see the PWA install instructions in README.md. */
export async function migrateLegacyLocalHistory(): Promise<void> {
  let rawIndex: string | null;
  try {
    rawIndex = localStorage.getItem(LEGACY_INDEX_KEY);
  } catch {
    return;
  }
  if (!rawIndex) return;

  type LegacyConversation = Partial<ConversationSummary> & { conversationId?: string };
  const legacyIndex = safeParseLegacy<LegacyConversation[]>(rawIndex, []);
  const legacyFolders = safeParseLegacy<Folder[]>(localStorage.getItem(LEGACY_FOLDERS_KEY), []);

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

  try {
    await dashboardApi.importHistory({ conversations, folders: legacyFolders });
  } catch {
    // Backend unreachable or erroring -- leave the legacy keys in place and
    // try again on the next startup rather than losing the only copy.
    return;
  }

  try {
    for (const entry of legacyIndex) {
      if (entry?.conversationId) {
        localStorage.removeItem(LEGACY_MESSAGES_PREFIX + entry.conversationId);
      }
    }
    localStorage.removeItem(LEGACY_INDEX_KEY);
    localStorage.removeItem(LEGACY_FOLDERS_KEY);
  } catch {
    // Storage unavailable for the cleanup step -- harmless: the import
    // already succeeded, and migrateLegacyLocalHistory() will just import
    // (a no-op, since the ids already exist server-side) again next time.
  }
}
