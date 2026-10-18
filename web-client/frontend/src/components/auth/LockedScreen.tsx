import { useT } from "../LanguageProvider";
import { Button } from "../dashboard/ui";
import { LockIcon } from "../ui/icons";

/** Shown when no password is configured yet (or the status check failed). */
export function LockedScreen({
  onRetry,
  errorMessage,
}: {
  onRetry: () => void;
  errorMessage?: string;
}) {
  const t = useT();
  return (
    <div className="flex min-h-dvh items-center justify-center bg-app px-4 py-8">
      <div className="w-full max-w-sm rounded-xl border border-line bg-panel p-5 text-center">
        <LockIcon className="mx-auto mb-3 h-8 w-8 text-fg-muted" />
        {errorMessage ? (
          <p role="alert" className="mb-4 text-sm text-danger-text">
            {errorMessage}
          </p>
        ) : (
          <>
            <h1 className="mb-2 text-base font-semibold text-fg">{t("auth.locked_title")}</h1>
            <p className="mb-3 text-sm text-fg-muted">{t("auth.locked_body")}</p>
            <code className="mb-4 block rounded-lg border border-line bg-code px-3 py-2 text-sm text-fg">
              {t("auth.locked_command")}
            </code>
          </>
        )}
        <Button onClick={onRetry} variant="primary">
          {t("auth.retry")}
        </Button>
      </div>
    </div>
  );
}
