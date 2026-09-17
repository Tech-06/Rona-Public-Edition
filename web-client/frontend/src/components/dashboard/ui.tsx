import type { ReactNode } from "react";

export function Card({
  title,
  children,
  actions,
}: {
  title?: string;
  children: ReactNode;
  actions?: ReactNode;
}) {
  return (
    <div className="rounded-xl border border-surface-border bg-surface-raised p-4">
      {(title || actions) && (
        <div className="mb-3 flex items-center justify-between gap-2">
          {title && <h3 className="text-sm font-semibold text-slate-200">{title}</h3>}
          {actions}
        </div>
      )}
      {children}
    </div>
  );
}

export function Badge({
  tone,
  children,
}: {
  tone: "ok" | "bad" | "neutral" | "warn";
  children: ReactNode;
}) {
  const styles: Record<typeof tone, string> = {
    ok: "bg-emerald-500/15 text-emerald-300",
    bad: "bg-rose-500/15 text-rose-300",
    warn: "bg-amber-500/15 text-amber-300",
    neutral: "bg-slate-500/15 text-slate-300",
  };
  const dots: Record<typeof tone, string> = {
    ok: "bg-emerald-400",
    bad: "bg-rose-400",
    warn: "bg-amber-400",
    neutral: "bg-slate-400",
  };
  return (
    <span className={`inline-flex items-center gap-1.5 rounded-full px-2 py-0.5 text-xs font-medium ${styles[tone]}`}>
      <span className={`h-1.5 w-1.5 rounded-full ${dots[tone]}`} />
      {children}
    </span>
  );
}

export function Button({
  children,
  onClick,
  variant = "default",
  disabled,
  type = "button",
}: {
  children: ReactNode;
  onClick?: () => void;
  variant?: "default" | "primary" | "danger";
  disabled?: boolean;
  type?: "button" | "submit";
}) {
  const styles: Record<typeof variant, string> = {
    default: "border border-surface-border text-slate-200 hover:bg-surface",
    primary: "bg-sky-600 text-white hover:bg-sky-500",
    danger: "bg-rose-600 text-white hover:bg-rose-500",
  };
  return (
    <button
      type={type}
      onClick={onClick}
      disabled={disabled}
      className={`rounded-lg px-3 py-1.5 text-xs font-medium transition-colors disabled:cursor-not-allowed disabled:opacity-40 ${styles[variant]}`}
    >
      {children}
    </button>
  );
}

export function EmptyState({ children }: { children: ReactNode }) {
  return <p className="py-6 text-center text-sm text-slate-500">{children}</p>;
}

export function ErrorState({ message }: { message: string }) {
  return (
    <p className="rounded-lg border border-rose-500/30 bg-rose-500/10 px-3 py-2 text-sm text-rose-300">
      {message}
    </p>
  );
}
