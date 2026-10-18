import { useEffect, useRef, useState, type FormEvent } from "react";
import { authApi } from "../../api/auth";
import { ApiError } from "../../api/client";
import { useT } from "../LanguageProvider";
import { LockIcon } from "../ui/icons";

export function LoginScreen({
  onAuthenticated,
  expired = false,
}: {
  onAuthenticated: () => void;
  expired?: boolean;
}) {
  const t = useT();
  const inputRef = useRef<HTMLInputElement>(null);
  const [password, setPassword] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [retrySeconds, setRetrySeconds] = useState(0);

  useEffect(() => {
    inputRef.current?.focus();
  }, []);

  useEffect(() => {
    if (retrySeconds <= 0) return;
    const id = setTimeout(() => setRetrySeconds((s) => s - 1), 1000);
    return () => clearTimeout(id);
  }, [retrySeconds]);

  const locked = retrySeconds > 0;

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (submitting || locked || !password) return;
    setSubmitting(true);
    setError(null);
    try {
      await authApi.login(password);
      setPassword("");
      onAuthenticated();
    } catch (err) {
      if (err instanceof ApiError && err.code === "invalid_password") {
        setError(t("auth.invalid_password"));
      } else if (err instanceof ApiError && err.code === "too_many_attempts") {
        setRetrySeconds(Math.max(1, Math.ceil(err.retryAfter ?? 1)));
      } else {
        setError(t("auth.login_failed"));
      }
      setPassword("");
      inputRef.current?.focus();
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="flex min-h-dvh items-center justify-center bg-app px-4 py-8">
      <form onSubmit={submit} className="w-full max-w-sm rounded-xl border border-line bg-panel p-5">
        <LockIcon className="mx-auto mb-3 h-8 w-8 text-fg-muted" />
        <h1 className="mb-1 text-center text-base font-semibold text-fg">{t("auth.login_title")}</h1>
        <p className="mb-4 text-center text-sm text-fg-muted">
          {expired ? t("auth.session_expired") : t("auth.login_subtitle")}
        </p>
        <label htmlFor="login-password" className="mb-1 block text-xs font-medium text-fg-soft">
          {t("auth.password_label")}
        </label>
        <input
          id="login-password"
          ref={inputRef}
          type="password"
          autoComplete="current-password"
          value={password}
          onChange={(event) => setPassword(event.target.value)}
          className="w-full rounded-lg border border-line bg-app px-3 py-2 text-base text-fg focus:border-accent focus:outline-none sm:text-sm"
        />
        <div className="min-h-[1.5rem] pt-2" aria-live="polite">
          {locked ? (
            <p role="alert" className="text-xs text-danger-text">
              {t("auth.too_many_attempts", { seconds: retrySeconds })}
            </p>
          ) : (
            error && (
              <p role="alert" className="text-xs text-danger-text">
                {error}
              </p>
            )
          )}
        </div>
        <button
          type="submit"
          disabled={submitting || locked || !password}
          className="mt-1 w-full rounded-lg bg-accent px-3 py-2 text-sm font-medium text-accent-fg transition-colors hover:bg-accent-hover disabled:cursor-not-allowed disabled:opacity-40"
        >
          {submitting ? t("auth.logging_in") : t("auth.login_button")}
        </button>
      </form>
    </div>
  );
}
