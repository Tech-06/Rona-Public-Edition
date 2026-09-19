import { useState, type KeyboardEvent } from "react";
import { useT } from "../LanguageProvider";
import { ArrowUpIcon, CheckIcon, XIcon } from "../ui/icons";

interface Props {
  onSend: (message: string) => void;
  disabled: boolean;
  awaitingConfirmation: boolean;
  onApprove: () => void;
  onReject: () => void;
}

export function Composer({ onSend, disabled, awaitingConfirmation, onApprove, onReject }: Props) {
  const t = useT();
  const [value, setValue] = useState("");

  function submit() {
    const trimmed = value.trim();
    if (!trimmed || disabled) return;
    onSend(trimmed);
    setValue("");
  }

  function handleKeyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      submit();
    }
  }

  // While a confirmation is pending, the approve/reject controls take the
  // send button's spot. Typing a free-text reply instead (the alternative
  // to clicking them) swaps them back out for the send button; clearing
  // the draft brings them back.
  const showConfirmActions = awaitingConfirmation && !value.trim();
  const canSend = !disabled && value.trim().length > 0;

  return (
    <div className="border-t border-line bg-app px-4 pb-[max(0.75rem,env(safe-area-inset-bottom))] pt-3">
      <div className="mx-auto flex w-full max-w-3xl flex-col gap-2">
        <div
          className={`flex items-end gap-2 rounded-full border px-4 py-2 transition-colors ${
            awaitingConfirmation ? "border-warn/60 bg-warn/[0.07]" : "border-line bg-panel"
          }`}
        >
          <textarea
            value={value}
            onChange={(event) => setValue(event.target.value)}
            onKeyDown={handleKeyDown}
            rows={1}
            placeholder={awaitingConfirmation ? t("composer.confirm_placeholder") : ""}
            className="max-h-40 flex-1 resize-none bg-transparent py-1 text-[16px] text-fg placeholder:text-fg-subtle focus:outline-none sm:text-[15px]"
          />
          {showConfirmActions ? (
            <div className="flex shrink-0 items-center gap-1.5">
              <button
                type="button"
                onClick={onApprove}
                disabled={disabled}
                aria-label={t("composer.approve")}
                className="flex h-8 w-8 items-center justify-center rounded-full bg-ok text-accent-fg transition-colors hover:bg-ok-hover disabled:opacity-40"
              >
                <CheckIcon className="h-4 w-4" />
              </button>
              <button
                type="button"
                onClick={onReject}
                disabled={disabled}
                aria-label={t("composer.reject")}
                className="flex h-8 w-8 items-center justify-center rounded-full bg-danger-strong text-accent-fg transition-colors hover:bg-danger-hover disabled:opacity-40"
              >
                <XIcon className="h-4 w-4" />
              </button>
            </div>
          ) : (
            <button
              type="button"
              onClick={submit}
              disabled={!canSend}
              aria-label={t("composer.send")}
              className={`flex h-8 w-8 shrink-0 items-center justify-center rounded-full transition-colors ${
                canSend ? "bg-accent text-accent-fg hover:bg-accent-hover" : "bg-elevated text-fg-faint"
              }`}
            >
              <ArrowUpIcon className="h-4 w-4" />
            </button>
          )}
        </div>
      </div>
    </div>
  );
}
