import { useState, type KeyboardEvent } from "react";

interface Props {
  onSend: (message: string) => void;
  disabled: boolean;
  awaitingConfirmation: boolean;
  onApprove: () => void;
  onReject: () => void;
}

export function Composer({ onSend, disabled, awaitingConfirmation, onApprove, onReject }: Props) {
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

  return (
    <div className="border-t border-surface-border bg-surface px-4 py-3">
      <div className="mx-auto flex w-full max-w-3xl flex-col gap-2">
        {awaitingConfirmation && (
          <div className="flex gap-2">
            <button
              type="button"
              onClick={onApprove}
              disabled={disabled}
              className="rounded-full bg-emerald-600 px-3 py-1 text-xs font-medium text-white transition-colors hover:bg-emerald-500 disabled:opacity-40"
            >
              Onayla
            </button>
            <button
              type="button"
              onClick={onReject}
              disabled={disabled}
              className="rounded-full bg-rose-600 px-3 py-1 text-xs font-medium text-white transition-colors hover:bg-rose-500 disabled:opacity-40"
            >
              Reddet
            </button>
          </div>
        )}
        <div
          className={`flex items-end gap-2 rounded-2xl border px-3 py-2 transition-colors ${
            awaitingConfirmation
              ? "border-amber-500/60 bg-amber-500/[0.07]"
              : "border-surface-border bg-surface-raised"
          }`}
        >
          <textarea
            value={value}
            onChange={(event) => setValue(event.target.value)}
            onKeyDown={handleKeyDown}
            rows={1}
            placeholder={awaitingConfirmation ? "Onaylıyor musun? Yanıtını yaz..." : "Rona'ya yaz..."}
            className="max-h-40 flex-1 resize-none bg-transparent text-[15px] text-slate-100 placeholder:text-slate-500 focus:outline-none"
          />
          <button
            type="button"
            onClick={submit}
            disabled={disabled || !value.trim()}
            className="rounded-full bg-sky-600 px-4 py-1.5 text-sm font-medium text-white transition-colors hover:bg-sky-500 disabled:opacity-40"
          >
            Gönder
          </button>
        </div>
      </div>
    </div>
  );
}
