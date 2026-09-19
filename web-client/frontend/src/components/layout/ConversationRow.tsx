import { useRef, useState, type KeyboardEvent } from "react";
import { dashboardApi } from "../../api/dashboard";
import { DND_MIME } from "../../lib/dnd";
import {
  notifyConversationsChanged,
  renameConversation,
  setConversationFolder,
  setConversationPinned,
} from "../../lib/storage";
import type { ConversationSummary, Folder } from "../../types";
import { useT } from "../LanguageProvider";
import { FolderIcon, MoreHorizontalIcon, PencilIcon, PinIcon, PinOffIcon, Trash2Icon } from "../ui/icons";
import { Menu, MenuItem, MenuSeparator } from "../ui/Menu";

interface Props {
  conversation: ConversationSummary;
  active: boolean;
  folders: Folder[];
  isMenuOpen: boolean;
  onOpenMenu: () => void;
  onCloseMenu: () => void;
  isRenaming: boolean;
  onStartRename: () => void;
  onCancelRename: () => void;
  onSelect: () => void;
  onRequestDelete: () => void;
  onAnnounce: (message: string) => void;
}

/** A single conversation row: draggable (desktop drag-to-folder), and a
 * "..." menu that is the ONLY path on touch and for keyboard/screen-reader
 * users, since HTML5 drag-and-drop has no touch equivalent. Every action
 * the drag gesture can do (move to folder) is also reachable from here. */
export function ConversationRow({
  conversation,
  active,
  folders,
  isMenuOpen,
  onOpenMenu,
  onCloseMenu,
  isRenaming,
  onStartRename,
  onCancelRename,
  onSelect,
  onRequestDelete,
  onAnnounce,
}: Props) {
  const t = useT();
  const triggerRef = useRef<HTMLButtonElement>(null);
  const [showFolderList, setShowFolderList] = useState(false);
  const [draftTitle, setDraftTitle] = useState(conversation.title);

  function openMenu() {
    setShowFolderList(false);
    onOpenMenu();
  }

  function commitRename() {
    const trimmed = draftTitle.trim();
    if (trimmed && trimmed !== conversation.title) {
      renameConversation(conversation.conversationId, trimmed);
      notifyConversationsChanged();
    }
    onCancelRename();
  }

  function handleRenameKeyDown(event: KeyboardEvent<HTMLInputElement>) {
    if (event.key === "Enter") {
      event.preventDefault();
      commitRename();
    } else if (event.key === "Escape") {
      event.preventDefault();
      setDraftTitle(conversation.title);
      onCancelRename();
    }
  }

  async function togglePin() {
    const nextPinned = !conversation.pinned;
    // Optimistic: write locally first so the UI reacts instantly, then
    // sync to the backend (pinning must reach the server so its TTL
    // purge actually exempts this conversation). On failure, revert the
    // local state rather than leave it out of sync with what the server
    // will still purge.
    setConversationPinned(conversation.conversationId, nextPinned);
    notifyConversationsChanged();
    onCloseMenu();
    try {
      await dashboardApi.setConversationPinned(conversation.conversationId, nextPinned);
      onAnnounce(nextPinned ? t("row.pinned") : t("row.unpinned"));
    } catch {
      setConversationPinned(conversation.conversationId, !nextPinned);
      notifyConversationsChanged();
      onAnnounce(t("row.pin_save_failed"));
    }
  }

  function moveToFolder(folderId: string | null, folderName: string | null) {
    setConversationFolder(conversation.conversationId, folderId);
    notifyConversationsChanged();
    onAnnounce(
      folderName
        ? t("row.moved_to_folder", { folder: folderName })
        : t("sidebar.conversation_removed_from_folder"),
    );
    onCloseMenu();
  }

  if (isRenaming) {
    return (
      <div className="px-1 py-0.5">
        <input
          autoFocus
          value={draftTitle}
          onChange={(event) => setDraftTitle(event.target.value)}
          onKeyDown={handleRenameKeyDown}
          onBlur={commitRename}
          className="w-full rounded-lg border border-accent bg-app px-2.5 py-1.5 text-sm text-fg focus:outline-none"
        />
      </div>
    );
  }

  return (
    <div
      draggable
      onDragStart={(event) => {
        event.dataTransfer.setData(DND_MIME, conversation.conversationId);
        // Firefox refuses to start a drag with no standard MIME type set.
        event.dataTransfer.setData("text/plain", conversation.title);
        event.dataTransfer.effectAllowed = "move";
      }}
      className={`group flex select-none items-center rounded-lg pr-1 transition-colors ${
        active ? "bg-app" : "hover:bg-elevated"
      }`}
    >
      <button
        type="button"
        onClick={onSelect}
        className={`flex min-w-0 flex-1 items-center gap-1.5 truncate rounded-lg px-2.5 py-1.5 text-left text-sm transition-colors ${
          active ? "text-fg" : "text-fg-muted group-hover:text-fg-soft"
        }`}
      >
        {conversation.pinned && <PinIcon className="h-3 w-3 shrink-0 text-fg-faint" />}
        <span className="truncate">{conversation.title || t("row.untitled_chat")}</span>
      </button>
      <button
        ref={triggerRef}
        type="button"
        draggable={false}
        onClick={(event) => {
          event.stopPropagation();
          openMenu();
        }}
        title={t("row.chat_menu")}
        aria-label={t("row.chat_menu")}
        className={`shrink-0 rounded-md px-1.5 py-1 text-fg-faint opacity-0 transition-opacity hover:text-fg-soft focus-visible:opacity-100 group-hover:opacity-100 ${
          isMenuOpen ? "opacity-100" : ""
        }`}
      >
        <MoreHorizontalIcon className="h-4 w-4" />
      </button>

      <Menu open={isMenuOpen} onClose={onCloseMenu} anchorRef={triggerRef}>
        {!showFolderList ? (
          <>
            <MenuItem
              label={t("row.rename")}
              icon={<PencilIcon className="h-4 w-4" />}
              onSelect={() => {
                setDraftTitle(conversation.title);
                onCloseMenu();
                onStartRename();
              }}
            />
            <MenuItem
              label={conversation.pinned ? t("row.unpin") : t("row.pin")}
              icon={conversation.pinned ? <PinOffIcon className="h-4 w-4" /> : <PinIcon className="h-4 w-4" />}
              onSelect={togglePin}
            />
            <MenuItem
              label={t("row.move_to_folder")}
              icon={<FolderIcon className="h-4 w-4" />}
              onSelect={() => setShowFolderList(true)}
            />
            <MenuSeparator />
            <MenuItem
              label={t("common.delete")}
              icon={<Trash2Icon className="h-4 w-4" />}
              danger
              onSelect={() => {
                onCloseMenu();
                onRequestDelete();
              }}
            />
          </>
        ) : (
          <>
            {conversation.folderId && (
              <MenuItem label={t("row.remove_from_folder")} onSelect={() => moveToFolder(null, null)} />
            )}
            {folders.length === 0 && (
              <p className="px-3 py-1.5 text-xs text-fg-subtle">{t("row.no_folders_yet")}</p>
            )}
            {folders.map((folder) => (
              <MenuItem
                key={folder.id}
                label={folder.name}
                icon={<FolderIcon className="h-4 w-4" />}
                onSelect={() => moveToFolder(folder.id, folder.name)}
              />
            ))}
          </>
        )}
      </Menu>
    </div>
  );
}
