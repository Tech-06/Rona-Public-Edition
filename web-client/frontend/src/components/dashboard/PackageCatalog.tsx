import { useState } from "react";
import { ApiError } from "../../api/client";
import { hostPackagesApi, type HostPackageEntry, type HostPackagePlan } from "../../api/hostPackages";
import { useT } from "../LanguageProvider";
import { ConfirmDialog } from "../ui/ConfirmDialog";
import { Badge, Button, EmptyState, ErrorState } from "./ui";

interface PendingPlan {
  id: string;
  plan: HostPackagePlan;
}

interface Props {
  entries: HostPackageEntry[] | null;
  loading: boolean;
  error: string | null;
  busy: boolean;
  onRefresh: () => void;
  onInstall: (id: string) => Promise<unknown>;
  onUpdate: (id: string) => Promise<unknown>;
}

/** The "Catalog" tab of ConnectionsPanel: every package the configured
 * source(s) offer, installed or not, with install/update entry points.
 * Library-kind packages (dependencies pulled in automatically) are never
 * shown here -- there's nothing to directly install/update about them. */
export function PackageCatalog({ entries, loading, error, busy, onRefresh, onInstall, onUpdate }: Props) {
  const t = useT();
  const [preparingId, setPreparingId] = useState<string | null>(null);
  const [prepareError, setPrepareError] = useState<{ id: string; message: string } | null>(null);
  const [pending, setPending] = useState<PendingPlan | null>(null);
  const [confirmBusy, setConfirmBusy] = useState(false);
  const [rowError, setRowError] = useState<{ id: string; message: string } | null>(null);

  async function prepare(id: string) {
    setPreparingId(id);
    setPrepareError(null);
    setRowError(null);
    try {
      const plan = await hostPackagesApi.plan(id);
      setPending({ id, plan });
    } catch (err) {
      setPrepareError({
        id,
        message: err instanceof ApiError ? err.message : t("common.action_failed"),
      });
    } finally {
      setPreparingId(null);
    }
  }

  async function confirm() {
    if (!pending) return;
    const { id, plan } = pending;
    setConfirmBusy(true);
    try {
      if (plan.action === "update") await onUpdate(id);
      else await onInstall(id);
      setPending(null);
    } catch (err) {
      setRowError({ id, message: err instanceof ApiError ? err.message : t("common.action_failed") });
      setPending(null);
    } finally {
      setConfirmBusy(false);
    }
  }

  const visible = (entries ?? []).filter((entry) => entry.kind !== "library");
  const showEmptyState = entries !== null && !loading && visible.length === 0;

  return (
    <div className="flex flex-col gap-2">
      <div className="flex items-center justify-end">
        <Button onClick={onRefresh} disabled={loading}>
          {loading ? t("connections.catalog_loading") : t("connections.catalog_refresh")}
        </Button>
      </div>

      {error && entries === null ? (
        <ErrorState message={error} />
      ) : loading && entries === null ? (
        <p className="py-4 text-center text-sm text-fg-subtle">{t("connections.catalog_loading")}</p>
      ) : showEmptyState ? (
        <EmptyState>{t("connections.catalog_empty")}</EmptyState>
      ) : (
        <div className="flex flex-col gap-2">
          {error && (
            <p className="text-xs text-fg-subtle">{t("connections.backend_restarting")}</p>
          )}
          {visible.map((entry) => (
            <div key={entry.id} className="rounded-lg border border-line bg-app px-3 py-2 text-sm">
              <div className="flex flex-wrap items-center gap-2">
                <div className="min-w-0 flex-1">
                  <p className="font-medium text-fg-soft">
                    {entry.name} <span className="text-xs text-fg-faint">{entry.id}</span>
                  </p>
                  {entry.description && <p className="text-xs text-fg-subtle">{entry.description}</p>}
                  {entry.requires && entry.requires.length > 0 && (
                    <p className="mt-0.5 break-words text-xs text-fg-faint">
                      {t("connections.requires")}: {entry.requires.join(", ")}
                    </p>
                  )}
                </div>
                <span className="shrink-0 text-xs text-fg-faint">{entry.version}</span>
                {entry.update_available ? (
                  <Badge tone="warn">
                    {t("connections.update_badge", {
                      from: entry.installed_version ?? "?",
                      to: entry.version,
                    })}
                  </Badge>
                ) : entry.installed ? (
                  <Badge tone="ok">{t("connections.installed_badge")}</Badge>
                ) : null}
                {(!entry.installed || entry.update_available) && (
                  <Button
                    variant="primary"
                    disabled={busy || preparingId !== null}
                    onClick={() => void prepare(entry.id)}
                  >
                    {preparingId === entry.id
                      ? t("connections.preparing")
                      : entry.installed
                        ? t("connections.update")
                        : t("connections.install")}
                  </Button>
                )}
              </div>
              {prepareError?.id === entry.id && (
                <p className="mt-2 text-xs text-danger-text">{prepareError.message}</p>
              )}
              {rowError?.id === entry.id && (
                <p className="mt-2 text-xs text-danger-text">{rowError.message}</p>
              )}
            </div>
          ))}
        </div>
      )}

      <ConfirmDialog
        open={pending !== null}
        title={
          pending
            ? t(
                pending.plan.action === "update"
                  ? "connections.plan_title_update"
                  : "connections.plan_title_install",
                { id: pending.id },
              )
            : ""
        }
        confirmLabel={
          pending
            ? pending.plan.action === "update"
              ? t("connections.update")
              : t("connections.install")
            : undefined
        }
        cancelLabel={t("common.cancel")}
        danger={false}
        confirmDisabled={confirmBusy}
        onConfirm={() => void confirm()}
        onCancel={() => setPending(null)}
      >
        {pending && (
          <div className="flex flex-col gap-1.5 text-xs text-fg-subtle">
            {pending.plan.entries
              .filter((entry) => entry.needs_action && entry.reason !== "requested")
              .map((entry) => (
                <p key={entry.id} className="font-mono">
                  {entry.reason === "upgrade"
                    ? t("connections.plan_upgrade", {
                        id: entry.id,
                        from: entry.installed_version ?? "?",
                        to: entry.version,
                      })
                    : t("connections.plan_dependency", { id: entry.id, version: entry.version })}
                </p>
              ))}
            {!pending.plan.complete && (
              <p className="text-warn-text">{t("connections.plan_incomplete")}</p>
            )}
            <p>{t("connections.plan_note")}</p>
          </div>
        )}
      </ConfirmDialog>
    </div>
  );
}
