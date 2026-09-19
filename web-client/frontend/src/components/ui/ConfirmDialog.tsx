import { useEffect, useRef } from "react";
import { createPortal } from "react-dom";
import { useFocusTrap } from "../../hooks/useFocusTrap";
import { useT } from "../LanguageProvider";
import { Button } from "../dashboard/ui";

interface Props {
  open: boolean;
  title: string;
  description?: string;
  confirmLabel?: string;
  cancelLabel?: string;
  danger?: boolean;
  onConfirm: () => void;
  onCancel: () => void;
}

/** Replaces native confirm()/prompt() dialogs, which can't be themed and
 * block the whole tab. Portal-rendered above everything else, including
 * the settings modal (z-60 > settings' z-50). */
export function ConfirmDialog({
  open,
  title,
  description,
  confirmLabel,
  cancelLabel,
  danger = true,
  onConfirm,
  onCancel,
}: Props) {
  const t = useT();
  const resolvedConfirmLabel = confirmLabel ?? t("common.delete");
  const resolvedCancelLabel = cancelLabel ?? t("common.cancel");
  const dialogRef = useRef<HTMLDivElement>(null);
  useFocusTrap(dialogRef, open, onCancel);

  useEffect(() => {
    if (!open) return;
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      document.body.style.overflow = previousOverflow;
    };
  }, [open]);

  if (!open) return null;

  return createPortal(
    <div className="fixed inset-0 z-[60] flex items-center justify-center bg-black/50 p-4">
      <button
        type="button"
        aria-label={resolvedCancelLabel}
        onClick={onCancel}
        className="absolute inset-0 cursor-default"
      />
      <div
        ref={dialogRef}
        role="alertdialog"
        aria-modal="true"
        aria-label={title}
        tabIndex={-1}
        className="relative flex w-full max-w-sm flex-col gap-3 rounded-xl border border-line bg-panel p-4 shadow-2xl outline-none"
      >
        <p className="text-sm font-semibold text-fg">{title}</p>
        {description && <p className="text-xs text-fg-subtle">{description}</p>}
        <div className="mt-1 flex justify-end gap-2">
          <Button onClick={onCancel}>{resolvedCancelLabel}</Button>
          <Button onClick={onConfirm} variant={danger ? "danger" : "primary"}>
            {resolvedConfirmLabel}
          </Button>
        </div>
      </div>
    </div>,
    document.body,
  );
}
