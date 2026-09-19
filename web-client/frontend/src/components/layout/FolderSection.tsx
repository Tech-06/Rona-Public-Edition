import { useRef, useState } from "react";
import { useDropTarget } from "../../hooks/useDropTarget";
import {
  deleteFolder,
  notifyConversationsChanged,
  renameFolder,
  setConversationFolder,
  setFolderCollapsed,
} from "../../lib/storage";
import type { ConversationSummary, Folder } from "../../types";
import { useT } from "../LanguageProvider";
import { ChevronRightIcon, FolderMinusIcon, MoreHorizontalIcon, PencilIcon } from "../ui/icons";
import { Menu, MenuItem, MenuSeparator } from "../ui/Menu";
import { ConversationRow } from "./ConversationRow";

interface Props {
  folder: Folder;
  conversations: ConversationSummary[];
  allFolders: Folder[];
  activeConversationId: string | null;
  openMenuId: string | null;
  onOpenMenu: (id: string) => void;
  onCloseMenu: () => void;
  renamingId: string | null;
  onStartRename: (id: string) => void;
  onCancelRename: () => void;
  onSelectConversation: (id: string) => void;
  onRequestDeleteConversation: (id: string) => void;
  onAnnounce: (message: string) => void;
}

export function FolderSection({
  folder,
  conversations,
  allFolders,
  activeConversationId,
  openMenuId,
  onOpenMenu,
  onCloseMenu,
  renamingId,
  onStartRename,
  onCancelRename,
  onSelectConversation,
  onRequestDeleteConversation,
  onAnnounce,
}: Props) {
  const t = useT();
  const folderTriggerRef = useRef<HTMLButtonElement>(null);
  const [folderMenuOpen, setFolderMenuOpen] = useState(false);
  const [isRenamingFolder, setIsRenamingFolder] = useState(false);
  const [draftName, setDraftName] = useState(folder.name);

  const { isOver, handlers } = useDropTarget((conversationId) => {
    setConversationFolder(conversationId, folder.id);
    notifyConversationsChanged();
    onAnnounce(t("row.moved_to_folder", { folder: folder.name }));
  });

  function commitRenameFolder() {
    const trimmed = draftName.trim();
    if (trimmed && trimmed !== folder.name) {
      renameFolder(folder.id, trimmed);
      notifyConversationsChanged();
    }
    setIsRenamingFolder(false);
  }

  return (
    <div className={`rounded-lg ${isOver ? "bg-accent/10 ring-1 ring-accent" : ""}`} {...handlers}>
      <div className="group flex items-center rounded-lg pr-1 hover:bg-elevated">
        <button
          type="button"
          onClick={() => {
            setFolderCollapsed(folder.id, !folder.collapsed);
            notifyConversationsChanged();
          }}
          className="flex min-w-0 flex-1 items-center gap-1.5 rounded-lg px-2.5 py-1.5 text-left text-sm text-fg-soft"
        >
          <ChevronRightIcon
            className={`h-3.5 w-3.5 shrink-0 transition-transform ${folder.collapsed ? "" : "rotate-90"}`}
          />
          {isRenamingFolder ? (
            <input
              autoFocus
              value={draftName}
              onChange={(event) => setDraftName(event.target.value)}
              onClick={(event) => event.stopPropagation()}
              onKeyDown={(event) => {
                if (event.key === "Enter") {
                  event.preventDefault();
                  commitRenameFolder();
                } else if (event.key === "Escape") {
                  event.preventDefault();
                  setDraftName(folder.name);
                  setIsRenamingFolder(false);
                }
              }}
              onBlur={commitRenameFolder}
              className="min-w-0 flex-1 rounded border border-accent bg-app px-1.5 py-0.5 text-sm text-fg focus:outline-none"
            />
          ) : (
            <span className="truncate">{folder.name}</span>
          )}
          <span className="ml-auto shrink-0 text-xs text-fg-faint">{conversations.length}</span>
        </button>
        <button
          ref={folderTriggerRef}
          type="button"
          onClick={(event) => {
            event.stopPropagation();
            setFolderMenuOpen(true);
          }}
          aria-label={t("folder.menu_label")}
          className={`shrink-0 rounded-md px-1.5 py-1 text-fg-faint opacity-0 transition-opacity hover:text-fg-soft focus-visible:opacity-100 group-hover:opacity-100 ${
            folderMenuOpen ? "opacity-100" : ""
          }`}
        >
          <MoreHorizontalIcon className="h-4 w-4" />
        </button>
        <Menu open={folderMenuOpen} onClose={() => setFolderMenuOpen(false)} anchorRef={folderTriggerRef}>
          <MenuItem
            label={t("row.rename")}
            icon={<PencilIcon className="h-4 w-4" />}
            onSelect={() => {
              setFolderMenuOpen(false);
              setDraftName(folder.name);
              setIsRenamingFolder(true);
            }}
          />
          <MenuSeparator />
          <MenuItem
            label={t("folder.delete")}
            icon={<FolderMinusIcon className="h-4 w-4" />}
            danger
            onSelect={() => {
              setFolderMenuOpen(false);
              deleteFolder(folder.id);
              notifyConversationsChanged();
              onAnnounce(t("folder.deleted_announcement", { name: folder.name }));
            }}
          />
        </Menu>
      </div>
      {!folder.collapsed && (
        <div className="ml-2 flex flex-col gap-0.5 border-l border-line pl-2">
          {conversations.length === 0 && (
            <p className="px-2.5 py-1 text-xs text-fg-faint">{t("folder.empty")}</p>
          )}
          {conversations.map((conversation) => (
            <ConversationRow
              key={conversation.conversationId}
              conversation={conversation}
              active={activeConversationId === conversation.conversationId}
              folders={allFolders}
              isMenuOpen={openMenuId === conversation.conversationId}
              onOpenMenu={() => onOpenMenu(conversation.conversationId)}
              onCloseMenu={onCloseMenu}
              isRenaming={renamingId === conversation.conversationId}
              onStartRename={() => onStartRename(conversation.conversationId)}
              onCancelRename={onCancelRename}
              onSelect={() => onSelectConversation(conversation.conversationId)}
              onRequestDelete={() => onRequestDeleteConversation(conversation.conversationId)}
              onAnnounce={onAnnounce}
            />
          ))}
        </div>
      )}
    </div>
  );
}
