import { useEffect, useRef } from "react";
import type { PackageJob } from "../../api/hostPackages";
import type { TranslationKey } from "../../lib/i18n";
import { useT } from "../LanguageProvider";
import { Badge, Button, Card, ErrorState } from "./ui";

const TITLE_KEYS: Record<PackageJob["action"], TranslationKey> = {
  install: "connections.job_title_install",
  update: "connections.job_title_update",
  uninstall: "connections.job_title_uninstall",
};

interface Props {
  job: PackageJob;
  /** Set by the parent while it's retrying `POST /api/packages/reload`
   * after this job finished -- the backend may still be mid-restart. */
  reloading: boolean;
  reloadFailed: boolean;
  onClose: () => void;
}

/** Shows one install/update/uninstall job's live log and, once it settles,
 * its outcome. Rendered by ConnectionsPanel above the installed/catalog
 * tabs so it survives a transient /api error (backend restarting)
 * clearing the rest of the panel's data. */
export function PackageJobPanel({ job, reloading, reloadFailed, onClose }: Props) {
  const t = useT();
  const endRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    endRef.current?.scrollIntoView({ block: "end" });
  }, [job.log_lines.length]);

  const badgeTone = job.state === "running" ? "warn" : job.state === "succeeded" ? "ok" : "bad";
  const badgeText =
    job.state === "running"
      ? t("connections.job_running")
      : job.state === "succeeded"
        ? t("connections.job_succeeded")
        : t("connections.job_failed");

  const configPendingIds = Object.keys(job.result?.config_pending ?? {});
  const unhealthy = Object.entries(job.result?.health ?? {}).filter(([, health]) => !health.ok);
  const finished = job.state !== "running";

  return (
    <Card
      title={t(TITLE_KEYS[job.action], { id: job.package_id })}
      actions={
        <div className="flex items-center gap-2">
          <Badge tone={badgeTone}>{badgeText}</Badge>
          {finished && <Button onClick={onClose}>{t("connections.job_close")}</Button>}
        </div>
      }
    >
      <div className="flex flex-col gap-2">
        <div className="max-h-72 overflow-y-auto rounded-xl border border-line bg-code p-3 font-mono text-xs text-fg-soft">
          {job.log_lines.length === 0 && <p className="text-fg-faint">…</p>}
          {job.log_lines.map((line, index) => (
            <div key={index} className="whitespace-pre-wrap break-all">
              {line}
            </div>
          ))}
          <div ref={endRef} />
        </div>

        {finished && (
          <div className="flex flex-col gap-2">
            {job.error && <ErrorState message={job.error} />}
            {configPendingIds.length > 0 && (
              <p className="rounded-lg border border-warn/40 bg-warn/10 px-3 py-2 text-xs text-warn-text">
                {t("connections.job_config_pending", { ids: configPendingIds.join(", ") })}
              </p>
            )}
            {unhealthy.map(([id, health]) => (
              <p
                key={id}
                className="rounded-lg border border-warn/40 bg-warn/10 px-3 py-2 text-xs text-warn-text"
              >
                {t("connections.job_unhealthy", { id, detail: health.detail })}
              </p>
            ))}
            {reloading && <p className="text-xs text-fg-subtle">{t("connections.job_reloading")}</p>}
            {reloadFailed && !reloading && (
              <p className="text-xs text-danger-text">{t("connections.job_reload_failed")}</p>
            )}
          </div>
        )}
      </div>
    </Card>
  );
}
