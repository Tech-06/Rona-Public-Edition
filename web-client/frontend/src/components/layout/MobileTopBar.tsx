import { useT } from "../LanguageProvider";
import { MenuIcon, PlusIcon } from "../ui/icons";

interface Props {
  onOpenDrawer: () => void;
  onNewChat: () => void;
}

/** Only visible below the md breakpoint - the desktop sidebar is always
 * visible and needs no top bar of its own. */
export function MobileTopBar({ onOpenDrawer, onNewChat }: Props) {
  const t = useT();
  return (
    <div className="flex items-center gap-1 border-b border-line bg-panel px-2 py-2.5 md:hidden">
      <button
        type="button"
        onClick={onOpenDrawer}
        aria-label={t("mobile.open_chats")}
        className="rounded-lg p-2 text-fg-muted transition-colors hover:bg-elevated hover:text-fg-soft"
      >
        <MenuIcon className="h-5 w-5" />
      </button>
      <span className="text-sm font-semibold text-fg">Rona</span>
      <button
        type="button"
        onClick={onNewChat}
        aria-label={t("sidebar.new_chat")}
        className="ml-auto rounded-lg p-2 text-fg-muted transition-colors hover:bg-elevated hover:text-fg-soft"
      >
        <PlusIcon className="h-5 w-5" />
      </button>
    </div>
  );
}
