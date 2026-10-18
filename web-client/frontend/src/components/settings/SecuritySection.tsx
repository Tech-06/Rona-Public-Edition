import { useState, type FormEvent } from "react";
import { authApi } from "../../api/auth";
import { ApiError } from "../../api/client";
import { useAuth } from "../auth/AuthProvider";
import { useT } from "../LanguageProvider";
import { Button, Card, ErrorState } from "../dashboard/ui";

export const MIN_PASSWORD_LENGTH = 4;

const INPUT_CLASS =
  "w-full max-w-xs rounded-lg border border-line bg-app px-2.5 py-1.5 text-sm text-fg focus:border-accent focus:outline-none";

export function SecuritySection() {
  const t = useT();
  const { logout } = useAuth();
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [confirm, setConfirm] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState(false);
  const [logoutError, setLogoutError] = useState<string | null>(null);

  async function submit(event: FormEvent) {
    event.preventDefault();
    setSuccess(false);
    if (!current) {
      setError(t("security.current_required"));
      return;
    }
    if (next.length < MIN_PASSWORD_LENGTH) {
      setError(t("security.too_short", { min: MIN_PASSWORD_LENGTH }));
      return;
    }
    if (next !== confirm) {
      setError(t("security.mismatch"));
      return;
    }
    setSaving(true);
    setError(null);
    try {
      await authApi.changePassword(current, next);
      setCurrent("");
      setNext("");
      setConfirm("");
      setSuccess(true);
    } catch (err) {
      if (err instanceof ApiError && err.code === "invalid_password") {
        setError(t("security.invalid_current"));
      } else if (err instanceof ApiError && err.code === "login_required") {
        // The global auth-required event already returns to the login form.
        setError(null);
      } else if (err instanceof ApiError && err.message) {
        // The BFF's detail is already localized.
        setError(err.message);
      } else {
        setError(t("security.change_failed"));
      }
    } finally {
      setSaving(false);
    }
  }

  async function handleLogout() {
    setLogoutError(null);
    try {
      await logout();
    } catch {
      setLogoutError(t("security.logout_failed"));
    }
  }

  return (
    <div className="flex flex-col gap-4">
      <Card title={t("security.change_title")}>
        <p className="mb-3 text-xs text-fg-subtle">
          {t("security.change_description", { min: MIN_PASSWORD_LENGTH })}
        </p>
        <form onSubmit={submit} className="flex flex-col gap-3">
          <label className="flex flex-col gap-1 text-xs font-medium text-fg-soft">
            {t("security.current_label")}
            <input
              type="password"
              autoComplete="current-password"
              value={current}
              onChange={(event) => setCurrent(event.target.value)}
              className={INPUT_CLASS}
            />
          </label>
          <label className="flex flex-col gap-1 text-xs font-medium text-fg-soft">
            {t("security.new_label")}
            <input
              type="password"
              autoComplete="new-password"
              value={next}
              onChange={(event) => setNext(event.target.value)}
              className={INPUT_CLASS}
            />
          </label>
          <label className="flex flex-col gap-1 text-xs font-medium text-fg-soft">
            {t("security.confirm_label")}
            <input
              type="password"
              autoComplete="new-password"
              value={confirm}
              onChange={(event) => setConfirm(event.target.value)}
              className={INPUT_CLASS}
            />
          </label>
          {error && <ErrorState message={error} />}
          {success && <p className="text-xs text-ok-text">{t("security.change_success")}</p>}
          <div>
            <Button type="submit" variant="primary" disabled={saving}>
              {saving ? t("security.changing") : t("security.change_button")}
            </Button>
          </div>
        </form>
      </Card>

      <Card title={t("security.logout_title")}>
        <p className="mb-3 text-xs text-fg-subtle">{t("security.logout_description")}</p>
        {logoutError && <ErrorState message={logoutError} />}
        <Button onClick={handleLogout} variant="danger">
          {t("security.logout_button")}
        </Button>
      </Card>
    </div>
  );
}
