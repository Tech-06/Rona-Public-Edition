import { useEffect, useMemo, useState, type KeyboardEvent } from "react";
import { useDropTarget } from "../../hooks/useDropTarget";
import {
  createFolder,
  loadFolders,
  notifyConversationsChanged,
  onConversationsChanged,
  setConversationFolder,
} from "../../lib/storage";
import type { ConversationSummary, Folder } from "../../types";
import { useT } from "../LanguageProvider";
import { ConfirmDialog } from "../ui/ConfirmDialog";
import { FolderPlusIcon, GearIcon } from "../ui/icons";
import { ConversationRow } from "./ConversationRow";
import { FolderSection } from "./FolderSection";

interface Props {
  /** Mobile-only: whether the drawer is slid into view. Desktop always
   * shows the sidebar and ignores this (md:translate-x-0 overrides it). */
  open: boolean;
  conversations: ConversationSummary[];
  activeConversationId: string | null;
  onSelectConversation: (id: string) => void;
  onDeleteConversation: (id: string) => void;
  onNewChat: () => void;
  onOpenSettings: () => void;
  backendUp: boolean | null;
}

export function Sidebar({
  open,
  conversations,
  activeConversationId,
  onSelectConversation,
  onDeleteConversation,
  onNewChat,
  onOpenSettings,
  backendUp,
}: Props) {
  const t = useT();
  const [folders, setFolders] = useState<Folder[]>(() => loadFolders());
  const [openMenuId, setOpenMenuId] = useState<string | null>(null);
  const [renamingId, setRenamingId] = useState<string | null>(null);
  const [pendingDeleteId, setPendingDeleteId] = useState<string | null>(null);
  const [creatingFolder, setCreatingFolder] = useState(false);
  const [newFolderName, setNewFolderName] = useState("");
  const [announcement, setAnnouncement] = useState("");

  useEffect(() => onConversationsChanged(() => setFolders(loadFolders())), []);

  const { pinned, byFolder, unfiled } = useMemo(() => {
    const pinnedList: ConversationSummary[] = [];
    const folderMap = new Map<string, ConversationSummary[]>();
    const unfiledList: ConversationSummary[] = [];
    for (const conversation of conversations) {
      if (conversation.pinned) {
        pinnedList.push(conversation);
        continue;
      }
      if (conversation.folderId) {
        const list = folderMap.get(conversation.folderId) ?? [];
        list.push(conversation);
        folderMap.set(conversation.folderId, list);
      } else {
        unfiledList.push(conversation);
      }
    }
    return { pinned: pinnedList, byFolder: folderMap, unfiled: unfiledList };
  }, [conversations]);

  const { isOver: unfiledIsOver, handlers: unfiledHandlers } = useDropTarget((conversationId) => {
    setConversationFolder(conversationId, null);
    notifyConversationsChanged();
    setAnnouncement(t("sidebar.conversation_removed_from_folder"));
  });

  function commitCreateFolder() {
    const trimmed = newFolderName.trim();
    if (trimmed) {
      createFolder(trimmed);
      notifyConversationsChanged();
    }
    setCreatingFolder(false);
    setNewFolderName("");
  }

  function handleNewFolderKeyDown(event: KeyboardEvent<HTMLInputElement>) {
    if (event.key === "Enter") {
      event.preventDefault();
      commitCreateFolder();
    } else if (event.key === "Escape") {
      event.preventDefault();
      setCreatingFolder(false);
      setNewFolderName("");
    }
  }

  function requestDelete(id: string) {
    setPendingDeleteId(id);
  }

  function confirmDelete() {
    if (pendingDeleteId) {
      onDeleteConversation(pendingDeleteId);
    }
    setPendingDeleteId(null);
  }

  return (
    <aside
      className={`fixed inset-y-0 left-0 z-40 flex h-full w-[260px] shrink-0 flex-col border-r border-line bg-panel transition-transform duration-200 md:static md:z-auto md:w-64 md:translate-x-0 ${
        open ? "translate-x-0" : "-translate-x-full"
      }`}
    >
      <div className="flex items-center gap-2 px-4 py-4">
        <div className="flex h-7 w-7 items-center justify-center rounded-full bg-accent text-sm font-semibold text-accent-fg">
          R
        </div>
        <span className="text-sm font-semibold text-fg">Rona</span>
        <span
          className={`ml-auto h-2 w-2 rounded-full ${
            backendUp === null ? "bg-fg-faint" : backendUp ? "bg-ok-hover" : "bg-danger"
          }`}
          title={
            backendUp === null
              ? t("sidebar.backend_checking")
              : backendUp
                ? t("sidebar.backend_up")
                : t("sidebar.backend_down")
          }
        />
      </div>

      <div className="px-3">
        <button
          type="button"
          onClick={onNewChat}
          className={`w-full rounded-lg border px-3 py-2 text-left text-sm transition-colors ${
            !activeConversationId
              ? "border-accent/50 bg-accent/10 text-accent-text"
              : "border-line text-fg-soft hover:bg-elevated"
          }`}
        >
          + {t("sidebar.new_chat")}
        </button>
      </div>

      <div className="mt-3 flex-1 overflow-y-auto overscroll-contain px-3">
        {pinned.length > 0 && (
          <div className="mb-3">
            <p className="px-1 pb-1 text-xs font-medium uppercase tracking-wide text-fg-subtle">
              {t("sidebar.pinned_heading")}
            </p>
            <div className="flex flex-col gap-0.5">
              {pinned.map((conversation) => (
                <ConversationRow
                  key={conversation.conversationId}
                  conversation={conversation}
                  active={activeConversationId === conversation.conversationId}
                  folders={folders}
                  isMenuOpen={openMenuId === conversation.conversationId}
                  onOpenMenu={() => setOpenMenuId(conversation.conversationId)}
                  onCloseMenu={() => setOpenMenuId(null)}
                  isRenaming={renamingId === conversation.conversationId}
                  onStartRename={() => setRenamingId(conversation.conversationId)}
                  onCancelRename={() => setRenamingId(null)}
                  onSelect={() => onSelectConversation(conversation.conversationId)}
                  onRequestDelete={() => requestDelete(conversation.conversationId)}
                  onAnnounce={setAnnouncement}
                />
              ))}
            </div>
          </div>
        )}

        {folders.length > 0 && (
          <div className="mb-3">
            <p className="px-1 pb-1 text-xs font-medium uppercase tracking-wide text-fg-subtle">
              {t("sidebar.folders_heading")}
            </p>
            <div className="flex flex-col gap-0.5">
              {folders.map((folder) => (
                <FolderSection
                  key={folder.id}
                  folder={folder}
                  conversations={byFolder.get(folder.id) ?? []}
                  allFolders={folders}
                  activeConversationId={activeConversationId}
                  openMenuId={openMenuId}
                  onOpenMenu={setOpenMenuId}
                  onCloseMenu={() => setOpenMenuId(null)}
                  renamingId={renamingId}
                  onStartRename={setRenamingId}
                  onCancelRename={() => setRenamingId(null)}
                  onSelectConversation={onSelectConversation}
                  onRequestDeleteConversation={requestDelete}
                  onAnnounce={setAnnouncement}
                />
              ))}
            </div>
          </div>
        )}

        <div>
          <div className="flex items-center justify-between px-1 pb-1">
            <p className="text-xs font-medium uppercase tracking-wide text-fg-subtle">
              {t("sidebar.chats_heading")}
            </p>
            <button
              type="button"
              onClick={() => {
                setCreatingFolder(true);
                setNewFolderName("");
              }}
              title={t("sidebar.new_folder")}
              aria-label={t("sidebar.new_folder")}
              className="rounded-md p-1 text-fg-faint transition-colors hover:bg-elevated hover:text-fg-soft"
            >
              <FolderPlusIcon className="h-3.5 w-3.5" />
            </button>
          </div>
          {creatingFolder && (
            <div className="px-1 pb-1.5">
              <input
                autoFocus
                value={newFolderName}
                onChange={(event) => setNewFolderName(event.target.value)}
                onKeyDown={handleNewFolderKeyDown}
                onBlur={commitCreateFolder}
                placeholder={t("sidebar.folder_name_placeholder")}
                className="w-full rounded-lg border border-accent bg-app px-2.5 py-1.5 text-sm text-fg focus:outline-none"
              />
            </div>
          )}
          <div
            {...unfiledHandlers}
            className={`flex flex-col gap-0.5 rounded-lg ${
              unfiledIsOver ? "bg-accent/10 ring-1 ring-accent" : ""
            }`}
          >
            {unfiled.map((conversation) => (
              <ConversationRow
                key={conversation.conversationId}
                conversation={conversation}
                active={activeConversationId === conversation.conversationId}
                folders={folders}
                isMenuOpen={openMenuId === conversation.conversationId}
                onOpenMenu={() => setOpenMenuId(conversation.conversationId)}
                onCloseMenu={() => setOpenMenuId(null)}
                isRenaming={renamingId === conversation.conversationId}
                onStartRename={() => setRenamingId(conversation.conversationId)}
                onCancelRename={() => setRenamingId(null)}
                onSelect={() => onSelectConversation(conversation.conversationId)}
                onRequestDelete={() => requestDelete(conversation.conversationId)}
                onAnnounce={setAnnouncement}
              />
            ))}
            {conversations.length === 0 && (
              <p className="px-2.5 py-1.5 text-xs text-fg-faint">{t("sidebar.no_chats_yet")}</p>
            )}
          </div>
        </div>
      </div>

      <div aria-live="polite" className="sr-only">
        {announcement}
      </div>

      <div className="border-t border-line px-3 py-3">
        <button
          type="button"
          onClick={onOpenSettings}
          className="flex w-full items-center gap-2.5 rounded-lg px-2.5 py-1.5 text-left text-sm text-fg-muted transition-colors hover:bg-elevated hover:text-fg-soft"
        >
          <GearIcon className="h-4 w-4 shrink-0" />
          {t("settings.modal_title")}
        </button>
      </div>

      <ConfirmDialog
        open={pendingDeleteId !== null}
        title={t("sidebar.delete_chat_title")}
        description={t("sidebar.delete_chat_description")}
        onCancel={() => setPendingDeleteId(null)}
        onConfirm={confirmDelete}
      />
    </aside>
  );
}
