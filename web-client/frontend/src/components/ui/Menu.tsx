import { useEffect, useLayoutEffect, useRef, useState, type ReactNode, type RefObject } from "react";
import { createPortal } from "react-dom";

const MENU_WIDTH = 208;

interface Props {
  open: boolean;
  onClose: () => void;
  anchorRef: RefObject<HTMLElement>;
  children: ReactNode;
}

/** A dropdown menu rendered through a portal at a fixed position computed
 * from the trigger's bounding rect. Needed because conversation rows live
 * inside an `overflow-y-auto` list - an absolutely-positioned menu inside
 * that list would get clipped at the list's edge instead of floating over
 * the rest of the app. */
export function Menu({ open, onClose, anchorRef, children }: Props) {
  const menuRef = useRef<HTMLDivElement>(null);
  const [position, setPosition] = useState<{ top: number; left: number } | null>(null);

  useLayoutEffect(() => {
    if (!open || !anchorRef.current) {
      setPosition(null);
      return;
    }
    const rect = anchorRef.current.getBoundingClientRect();
    const left = Math.min(rect.left, window.innerWidth - MENU_WIDTH - 8);
    const top = Math.min(rect.bottom + 4, window.innerHeight - 8);
    setPosition({ top, left: Math.max(8, left) });
  }, [open, anchorRef]);

  useEffect(() => {
    if (!open) return;

    function handlePointerDown(event: PointerEvent) {
      const target = event.target as Node;
      if (menuRef.current?.contains(target)) return;
      if (anchorRef.current?.contains(target)) return;
      onClose();
    }
    function handleKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape") onClose();
    }
    function handleDismiss() {
      onClose();
    }

    document.addEventListener("pointerdown", handlePointerDown);
    document.addEventListener("keydown", handleKeyDown);
    // Capture phase so a scroll inside any ancestor (the conversation
    // list, the page) closes the menu instead of leaving it floating over
    // content it's no longer anchored to.
    window.addEventListener("scroll", handleDismiss, true);
    window.addEventListener("resize", handleDismiss);
    return () => {
      document.removeEventListener("pointerdown", handlePointerDown);
      document.removeEventListener("keydown", handleKeyDown);
      window.removeEventListener("scroll", handleDismiss, true);
      window.removeEventListener("resize", handleDismiss);
    };
  }, [open, onClose, anchorRef]);

  if (!open || !position) return null;

  return createPortal(
    <div
      ref={menuRef}
      role="menu"
      style={{ position: "fixed", top: position.top, left: position.left, width: MENU_WIDTH }}
      className="z-[70] overflow-hidden rounded-lg border border-line bg-panel py-1 shadow-2xl"
    >
      {children}
    </div>,
    document.body,
  );
}

export function MenuItem({
  label,
  onSelect,
  icon,
  danger,
}: {
  label: string;
  onSelect: () => void;
  icon?: ReactNode;
  danger?: boolean;
}) {
  return (
    <button
      type="button"
      role="menuitem"
      onClick={onSelect}
      className={`flex w-full items-center gap-2 px-3 py-1.5 text-left text-sm transition-colors ${
        danger ? "text-danger-text hover:bg-danger/10" : "text-fg-soft hover:bg-elevated"
      }`}
    >
      {icon}
      <span className="truncate">{label}</span>
    </button>
  );
}

export function MenuSeparator() {
  return <div role="separator" className="my-1 h-px bg-line" />;
}
