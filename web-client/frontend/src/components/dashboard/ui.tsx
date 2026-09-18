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
    <div className="overflow-hidden rounded-xl border border-line bg-panel p-3 sm:p-4">
      {(title || actions) && (
        <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
          {title && <h3 className="text-sm font-semibold text-fg-soft">{title}</h3>}
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
    ok: "bg-ok/15 text-ok-text",
    bad: "bg-danger/15 text-danger-text",
    warn: "bg-warn/15 text-warn-text",
    neutral: "bg-fg-subtle/15 text-fg-soft",
  };
  const dots: Record<typeof tone, string> = {
    ok: "bg-ok-hover",
    bad: "bg-danger-hover",
    warn: "bg-warn",
    neutral: "bg-fg-muted",
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
    default: "border border-line text-fg-soft hover:bg-elevated",
    primary: "bg-accent text-accent-fg hover:bg-accent-hover",
    danger: "bg-danger-strong text-accent-fg hover:bg-danger-hover",
  };
  return (
    <button
      type={type}
      onClick={onClick}
      disabled={disabled}
      className={`whitespace-nowrap rounded-lg px-3 py-1.5 text-xs font-medium transition-colors disabled:cursor-not-allowed disabled:opacity-40 ${styles[variant]}`}
    >
      {children}
    </button>
  );
}

export function EmptyState({ children }: { children: ReactNode }) {
  return <p className="py-6 text-center text-sm text-fg-subtle">{children}</p>;
}

export function ErrorState({ message }: { message: string }) {
  return (
    <p className="rounded-lg border border-danger/30 bg-danger/10 px-3 py-2 text-sm text-danger-text">
      {message}
    </p>
  );
}
