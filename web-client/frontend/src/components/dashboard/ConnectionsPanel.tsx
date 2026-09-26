import { useCallback, useEffect, useMemo, useState } from "react";
import { ApiError } from "../../api/client";
import {
  dashboardApi,
  type PackageAction,
  type PackageConfigField,
  type PackageStatus,
  type ProbeResponse,
  type ProbeResult,
} from "../../api/dashboard";
import {
  hostPackagesApi,
  type HostPackageEntry,
  type HostPackagePlan,
  type HostPackagesAvailable,
  type PackageJob,
} from "../../api/hostPackages";
import { usePackageJob } from "../../hooks/usePackageJob";
import { usePoll } from "../../hooks/usePoll";
import { useT } from "../LanguageProvider";
import { RestartBanner } from "../settings/RestartBanner";
import { ConfirmDialog } from "../ui/ConfirmDialog";
import { PackageCatalog } from "./PackageCatalog";
import { PackageJobPanel } from "./PackageJobPanel";
import { Badge, Button, Card, ErrorState } from "./ui";

type PackagesTab = "installed" | "catalog";

export function ConnectionsPanel() {
  const t = useT();
  const connections = usePoll(useCallback(() => dashboardApi.connections(), []), 15000);
  const server = usePoll(useCallback(() => dashboardApi.serverStatus(), []), null);
  const [probe, setProbe] = useState<ProbeResponse | null>(null);
  const [probing, setProbing] = useState(false);
  const [probeError, setProbeError] = useState<string | null>(null);
  const [restarting, setRestarting] = useState(false);

  const [tab, setTab] = useState<PackagesTab>("installed");
  const [openIds, setOpenIds] = useState<Set<string>>(new Set());

  const [catalogData, setCatalogData] = useState<HostPackagesAvailable | null>(null);
  const [catalogLoading, setCatalogLoading] = useState(false);
  const [catalogError, setCatalogError] = useState<string | null>(null);

  const [reloading, setReloading] = useState(false);
  const [reloadFailed, setReloadFailed] = useState(false);
  const [restartBannerVisible, setRestartBannerVisible] = useState(false);

  const fetchCatalog = useCallback(
    async (refresh = false) => {
      setCatalogLoading(true);
      try {
        const data = await hostPackagesApi.available(refresh);
        setCatalogData(data);
        setCatalogError(null);
      } catch (err) {
        setCatalogError(err instanceof ApiError ? err.message : t("connections.catalog_error"));
      } finally {
        setCatalogLoading(false);
      }
    },
    [t],
  );

  // Fetched once up front (not lazily when the Catalog tab is opened) so
  // the Installed tab's rows can show an Update button immediately, based
  // on the same data.
  useEffect(() => {
    void fetchCatalog(false);
  }, [fetchCatalog]);

  const catalogById = useMemo(() => {
    const map = new Map<string, HostPackageEntry>();
    for (const entry of catalogData?.packages ?? []) map.set(entry.id, entry);
    return map;
  }, [catalogData]);

  const handleJobFinished = useCallback(
    async (finishedJob: PackageJob) => {
      setReloading(true);
      setReloadFailed(false);
      const ok = await reloadPackagesWithRetry();
      setReloading(false);
      setReloadFailed(!ok);

      connections.refresh();
      void fetchCatalog(true);
      setTab("installed");

      const pendingIds = new Set(Object.keys(finishedJob.result?.config_pending ?? {}));
      if (finishedJob.action !== "uninstall") {
        try {
          const fresh = await dashboardApi.connections();
          const root = fresh.packages.find((item) => item.id === finishedJob.package_id);
          if (root && !root.configured) pendingIds.add(root.id);
        } catch {
          // best effort only -- the panel simply won't auto-open in this case
        }
      }
      if (pendingIds.size > 0) {
        setOpenIds((current) => new Set([...current, ...pendingIds]));
      }

      setRestartBannerVisible(Boolean(finishedJob.result?.restart_recommended) || !ok);
    },
    [connections, fetchCatalog],
  );

  const job = usePackageJob(handleJobFinished);

  async function runProbe() {
    setProbing(true);
    setProbeError(null);
    try {
      setProbe(await dashboardApi.probeConnections());
    } catch (err) {
      setProbeError(err instanceof Error ? err.message : t("connections.probe_failed"));
    } finally {
      setProbing(false);
    }
  }

  async function restartNow() {
    setRestarting(true);
    try {
      await dashboardApi.serverAction("restart");
      setRestartBannerVisible(false);
    } finally {
      setRestarting(false);
      server.refresh();
    }
  }

  function toggleOpen(id: string) {
    setOpenIds((current) => {
      const next = new Set(current);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  const canAutoRestart = Boolean(
    server.data && (server.data.tracked_process_alive || server.data.systemctl_available),
  );

  // Only the total absence of data blanks the section out -- a poll error
  // while a package job is running (the backend restarting mid-install)
  // must not make the job log above disappear along with everything else.
  const showConnectionsError = Boolean(connections.error) && !connections.data;

  return (
    <div className="flex flex-col gap-4">
      {job.job && (
        <PackageJobPanel job={job.job} reloading={reloading} reloadFailed={reloadFailed} onClose={job.dismiss} />
      )}

      <RestartBanner
        visible={restartBannerVisible}
        onRestart={restartNow}
        canAutoRestart={canAutoRestart}
        restarting={restarting}
      />

      {showConnectionsError ? (
        <ErrorState message={connections.error as string} />
      ) : (
        connections.data && (
          <>
            {connections.error && (
              <p className="text-xs text-fg-subtle">{t("connections.backend_restarting")}</p>
            )}

            <Card
              title={t("connections.title")}
              actions={
                <Button onClick={runProbe} disabled={probing} variant="primary">
                  {probing ? t("connections.probing") : t("connections.probe_now")}
                </Button>
              }
            >
              {probeError && <ErrorState message={probeError} />}
              <div className="grid grid-cols-[repeat(auto-fit,minmax(240px,1fr))] gap-2">
                <ConnectionRow label={t("connections.flash_model")} ok={connections.data.flash_configured} probe={probe?.llm} />
                <ConnectionRow label={t("connections.pro_model")} ok={connections.data.pro_configured} />
                <ConnectionRow
                  label={t("connections.gemini_embedding")}
                  ok={connections.data.gemini_embedding_configured}
                />
                <ConnectionRow label="rona.db" ok={connections.data.db_present} />
                <ConnectionRow label={t("connections.checkpoint_db")} ok={connections.data.checkpoint_db_present} />
              </div>
            </Card>

            <Card title={t("connections.packages_title")}>
              <div className="mb-3 flex gap-1.5">
                <TabButton active={tab === "installed"} onClick={() => setTab("installed")}>
                  {t("connections.tab_installed")}
                </TabButton>
                <TabButton active={tab === "catalog"} onClick={() => setTab("catalog")}>
                  {t("connections.tab_catalog")}
                </TabButton>
              </div>

              {tab === "installed" ? (
                connections.data.packages.length === 0 ? (
                  <div className="flex flex-col items-center gap-2 py-6 text-center text-sm text-fg-subtle">
                    <p>{t("connections.no_packages")}</p>
                    <Button variant="primary" onClick={() => setTab("catalog")}>
                      {t("connections.browse_catalog")}
                    </Button>
                  </div>
                ) : (
                  <div className="flex flex-col gap-2">
                    {connections.data.packages.map((pkg) => (
                      <PackageRow
                        key={pkg.id}
                        pkg={pkg}
                        probe={probe?.packages[pkg.id]}
                        open={openIds.has(pkg.id)}
                        onToggle={() => toggleOpen(pkg.id)}
                        catalogEntry={catalogById.get(pkg.id)}
                        busy={job.busy}
                        onUpdate={(id) => job.start("update", id)}
                        onUninstall={(id, purge) => job.start("uninstall", id, purge)}
                        onChanged={connections.refresh}
                      />
                    ))}
                  </div>
                )
              ) : (
                <PackageCatalog
                  entries={catalogData?.packages ?? null}
                  loading={catalogLoading}
                  error={catalogError}
                  busy={job.busy}
                  onRefresh={() => void fetchCatalog(true)}
                  onInstall={(id) => job.start("install", id)}
                  onUpdate={(id) => job.start("update", id)}
                />
              )}
            </Card>
          </>
        )
      )}
    </div>
  );
}

/** Retries `POST /api/packages/reload` up to 20 times, 1.5s apart, so a
 * backend that's mid-restart (RELOAD=true watches the files a package
 * install/update just wrote) doesn't turn into a permanent failure. Any
 * non-502/503/504 failure (or
 * running out of attempts) is reported as a failure to the caller, which
 * shows the restart banner instead of silently leaving stale package data
 * on screen. */
async function reloadPackagesWithRetry(): Promise<boolean> {
  for (let attempt = 0; attempt < 20; attempt++) {
    try {
      await dashboardApi.reloadPackages();
      return true;
    } catch (err) {
      const status = err instanceof ApiError ? err.status : 0;
      if (status === 502 || status === 503 || status === 504) {
        await new Promise((resolve) => setTimeout(resolve, 1500));
        continue;
      }
      return false;
    }
  }
  return false;
}

function TabButton({
  active,
  onClick,
  children,
}: {
  active: boolean;
  onClick: () => void;
  children: string;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={`rounded-full px-3 py-1.5 text-sm transition-colors ${
        active ? "bg-accent text-accent-fg" : "border border-line text-fg-muted hover:text-fg-soft"
      }`}
    >
      {children}
    </button>
  );
}

function PackageRow({
  pkg,
  probe,
  open,
  onToggle,
  catalogEntry,
  busy,
  onUpdate,
  onUninstall,
  onChanged,
}: {
  pkg: PackageStatus;
  probe?: ProbeResult;
  open: boolean;
  onToggle: () => void;
  catalogEntry?: HostPackageEntry;
  busy: boolean;
  onUpdate: (id: string) => Promise<unknown>;
  onUninstall: (id: string, purge: boolean) => Promise<unknown>;
  onChanged: () => void;
}) {
  const t = useT();
  // Nothing to show for a package that needs neither configuring nor any
  // operator action -- most of them.
  const hasPanel = pkg.config_fields.length > 0 || pkg.actions.length > 0;

  const [updatePlan, setUpdatePlan] = useState<HostPackagePlan | null>(null);
  const [updatePreparing, setUpdatePreparing] = useState(false);
  const [updateConfirmBusy, setUpdateConfirmBusy] = useState(false);
  const [updateError, setUpdateError] = useState<string | null>(null);

  const [uninstallOpen, setUninstallOpen] = useState(false);
  const [purge, setPurge] = useState(false);
  const [uninstallBusy, setUninstallBusy] = useState(false);
  const [uninstallError, setUninstallError] = useState<string | null>(null);

  async function prepareUpdate() {
    setUpdatePreparing(true);
    setUpdateError(null);
    try {
      setUpdatePlan(await hostPackagesApi.plan(pkg.id));
    } catch (err) {
      setUpdateError(err instanceof ApiError ? err.message : t("common.action_failed"));
    } finally {
      setUpdatePreparing(false);
    }
  }

  async function confirmUpdate() {
    setUpdateConfirmBusy(true);
    try {
      await onUpdate(pkg.id);
      setUpdatePlan(null);
    } catch (err) {
      setUpdateError(err instanceof ApiError ? err.message : t("common.action_failed"));
      setUpdatePlan(null);
    } finally {
      setUpdateConfirmBusy(false);
    }
  }

  async function confirmUninstall() {
    setUninstallBusy(true);
    setUninstallError(null);
    try {
      await onUninstall(pkg.id, purge);
      setUninstallOpen(false);
    } catch (err) {
      setUninstallError(err instanceof ApiError ? err.message : t("common.action_failed"));
    } finally {
      setUninstallBusy(false);
    }
  }

  const blocked = pkg.dependents.length > 0;

  return (
    <div className="rounded-lg border border-line bg-app">
      <div className="flex flex-wrap items-center gap-2 px-3 py-2 text-sm">
        <div className="min-w-0 flex-1">
          <p className="font-medium text-fg-soft">{pkg.name}</p>
          <p className="text-xs text-fg-subtle">{pkg.description}</p>
        </div>
        <Badge tone={pkg.configured ? "ok" : "warn"}>
          {pkg.configured
            ? t("common.configured")
            : t("connections.missing", { fields: pkg.missing_config.join(", ") })}
        </Badge>
        {pkg.requirement_problems.length > 0 && (
          <Badge tone="warn">
            {t("connections.requirement_problem", { detail: pkg.requirement_problems.join("; ") })}
          </Badge>
        )}
        {probe && (
          <Badge tone={probe.ok ? "ok" : "bad"}>{probe.ok ? t("connections.live") : probe.detail}</Badge>
        )}
        {catalogEntry?.update_available && (
          <Button
            variant="primary"
            disabled={busy || updatePreparing}
            onClick={() => void prepareUpdate()}
          >
            {updatePreparing ? t("connections.preparing") : t("connections.update")}
          </Button>
        )}
        <Button variant="danger" disabled={busy} onClick={() => setUninstallOpen(true)}>
          {t("connections.uninstall")}
        </Button>
        {hasPanel && (
          <Button onClick={onToggle}>
            {open ? t("connections.close") : t("connections.configure")}
          </Button>
        )}
      </div>

      {updateError && <p className="px-3 pb-2 text-xs text-danger-text">{updateError}</p>}
      {uninstallError && <p className="px-3 pb-2 text-xs text-danger-text">{uninstallError}</p>}

      {open && hasPanel && <PackagePanel pkg={pkg} onChanged={onChanged} />}

      <ConfirmDialog
        open={updatePlan !== null}
        title={t("connections.plan_title_update", { id: pkg.id })}
        confirmLabel={t("connections.update")}
        cancelLabel={t("common.cancel")}
        danger={false}
        confirmDisabled={updateConfirmBusy}
        onConfirm={() => void confirmUpdate()}
        onCancel={() => setUpdatePlan(null)}
      >
        {updatePlan && <PlanSummary plan={updatePlan} />}
      </ConfirmDialog>

      <ConfirmDialog
        open={uninstallOpen}
        title={t("connections.uninstall_title", { id: pkg.id })}
        confirmLabel={t("connections.uninstall")}
        cancelLabel={t("common.cancel")}
        danger
        confirmDisabled={blocked || uninstallBusy}
        onConfirm={() => void confirmUninstall()}
        onCancel={() => setUninstallOpen(false)}
      >
        {blocked ? (
          <div className="flex flex-col gap-1 text-xs">
            <p className="text-fg-soft">
              <span className="font-medium">{t("connections.dependents")}</span> {pkg.dependents.join(", ")}
            </p>
            <p className="text-danger-text">{t("connections.uninstall_blocked")}</p>
          </div>
        ) : (
          <label className="flex items-center gap-2 text-xs text-fg-soft">
            <input
              type="checkbox"
              checked={purge}
              onChange={(event) => setPurge(event.target.checked)}
              className="h-4 w-4 accent-accent"
            />
            {t("connections.uninstall_purge")}
          </label>
        )}
      </ConfirmDialog>
    </div>
  );
}

/** The dependency/upgrade breakdown shown inside an install/update confirm
 * dialog -- shared by the Installed tab's own Update button (here) and
 * PackageCatalog's install/update flow. */
function PlanSummary({ plan }: { plan: HostPackagePlan }) {
  const t = useT();
  return (
    <div className="flex flex-col gap-1.5 text-xs text-fg-subtle">
      {plan.entries
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
      {!plan.complete && <p className="text-warn-text">{t("connections.plan_incomplete")}</p>}
      <p>{t("connections.plan_note")}</p>
    </div>
  );
}

function PackagePanel({ pkg, onChanged }: { pkg: PackageStatus; onChanged: () => void }) {
  const t = useT();
  const [fields, setFields] = useState<PackageConfigField[] | null>(null);
  const [draft, setDraft] = useState<Record<string, unknown>>({});
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [health, setHealth] = useState<ProbeResult | null>(null);
  const [restartRequired, setRestartRequired] = useState(false);

  const load = useCallback(async () => {
    setError(null);
    try {
      setFields((await dashboardApi.packageConfig(pkg.id)).fields);
      setDraft({});
    } catch (err) {
      setError(err instanceof Error ? err.message : t("connections.config_load_failed"));
    }
  }, [pkg.id, t]);

  useEffect(() => {
    void load();
  }, [load]);

  async function save() {
    if (Object.keys(draft).length === 0) return;
    setSaving(true);
    setError(null);
    try {
      const result = await dashboardApi.updatePackageConfig(pkg.id, draft);
      setHealth(result.health);
      setRestartRequired(result.restart_required);
      await load();
      onChanged();
    } catch (err) {
      setError(err instanceof Error ? err.message : t("common.save_failed"));
    } finally {
      setSaving(false);
    }
  }

  const dirty = Object.keys(draft).length > 0;

  return (
    <div className="flex flex-col gap-3 border-t border-line px-3 py-3">
      {error && <ErrorState message={error} />}

      {fields && fields.length > 0 && (
        <div className="flex flex-col gap-3">
          {fields.map((field) => (
            <FieldRow
              key={field.key}
              field={field}
              draft={draft}
              onChange={(value) => setDraft((current) => ({ ...current, [field.key]: value }))}
            />
          ))}
          <div className="flex flex-wrap items-center gap-2">
            <Button onClick={save} variant="primary" disabled={!dirty || saving}>
              {saving ? t("common.saving") : t("common.save")}
            </Button>
            {health && (
              <Badge tone={health.ok ? "ok" : "warn"}>{health.detail || t("common.configured")}</Badge>
            )}
          </div>
          {restartRequired && (
            <p className="rounded-lg border border-warn/40 bg-warn/10 px-3 py-2 text-xs text-warn-text">
              {t("restart.required_message")}
            </p>
          )}
        </div>
      )}

      {pkg.actions.length > 0 && (
        <ActionSection
          pkg={pkg}
          onFinished={() => {
            void load();
            onChanged();
          }}
        />
      )}
    </div>
  );
}

/** One config field. `file` fields hold a path on the machine the backend
 * runs on, not on the viewer's -- there is no meaningful file picker for
 * that, so it stays a text field with its description explaining it. */
function FieldRow({
  field,
  draft,
  onChange,
}: {
  field: PackageConfigField;
  draft: Record<string, unknown>;
  onChange: (value: unknown) => void;
}) {
  const t = useT();
  const pending = field.key in draft;
  const current = pending ? draft[field.key] : field.value;

  const inputClass =
    "w-full rounded-lg border border-line bg-app px-2.5 py-1.5 text-sm text-fg focus:border-accent focus:outline-none";

  function renderInput() {
    if (field.type === "boolean") {
      return (
        <input
          type="checkbox"
          checked={Boolean(current)}
          onChange={(event) => onChange(event.target.checked)}
          className="h-4 w-4 accent-accent"
        />
      );
    }
    if (field.secret) {
      return (
        <input
          type="password"
          value={pending ? String(current ?? "") : ""}
          placeholder={field.set ? t("connections.secret_set") : t("connections.secret_unset")}
          onChange={(event) => onChange(event.target.value)}
          className={inputClass}
          autoComplete="off"
        />
      );
    }
    if (field.type === "integer") {
      return (
        <input
          type="number"
          value={current === null || current === undefined ? "" : String(current)}
          onChange={(event) => onChange(event.target.value === "" ? null : Number(event.target.value))}
          className={inputClass}
        />
      );
    }
    if (field.type === "list") {
      const shown = Array.isArray(current) ? current.join(", ") : String(current ?? "");
      return (
        <input
          type="text"
          value={shown}
          placeholder={t("connections.list_placeholder")}
          onChange={(event) =>
            onChange(
              event.target.value
                .split(",")
                .map((item) => item.trim())
                .filter(Boolean),
            )
          }
          className={inputClass}
        />
      );
    }
    return (
      <input
        type="text"
        value={current === null || current === undefined ? "" : String(current)}
        onChange={(event) => onChange(event.target.value)}
        className={inputClass}
      />
    );
  }

  return (
    <label className="flex flex-col gap-1">
      <span className="text-xs font-medium text-fg-soft">
        {field.label}
        {field.required && <span className="text-danger-text"> *</span>}
      </span>
      {renderInput()}
      {field.description && <span className="text-xs text-fg-subtle">{field.description}</span>}
    </label>
  );
}

interface RunningAction {
  action: PackageAction;
  /** What to ask for right now: the action's own params on the first step,
   * whatever the handler asked for on later ones. */
  fields: PackageConfigField[];
  message: string;
  /** Opaque blob from the previous step, handed back untouched. */
  state: Record<string, unknown> | null;
  values: Record<string, unknown>;
}

function ActionSection({ pkg, onFinished }: { pkg: PackageStatus; onFinished: () => void }) {
  const t = useT();
  const [running, setRunning] = useState<RunningAction | null>(null);
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<{ ok: boolean; message: string } | null>(null);
  const [confirming, setConfirming] = useState<PackageAction | null>(null);

  const submit = useCallback(
    async (action: PackageAction, values: Record<string, unknown>, state: Record<string, unknown> | null) => {
      setBusy(true);
      setResult(null);
      try {
        const response = await dashboardApi.runPackageAction(pkg.id, action.id, values, state);
        if (response.status === "input_required") {
          setRunning({
            action,
            fields: response.fields,
            message: response.message,
            state: response.state,
            values: {},
          });
          return;
        }
        setRunning(null);
        setResult({ ok: response.status === "ok", message: response.message });
        if (response.status === "ok") onFinished();
      } catch (err) {
        setRunning(null);
        setResult({
          ok: false,
          message: err instanceof Error ? err.message : t("common.action_failed"),
        });
      } finally {
        setBusy(false);
      }
    },
    [pkg.id, onFinished, t],
  );

  function start(action: PackageAction) {
    setResult(null);
    if (action.params.length === 0) {
      void submit(action, {}, null);
      return;
    }
    setRunning({
      action,
      fields: action.params,
      message: action.description,
      state: null,
      values: {},
    });
  }

  return (
    <div className="flex flex-col gap-2 border-t border-line pt-3">
      <p className="text-xs font-medium text-fg-soft">{t("connections.actions_title")}</p>
      <div className="flex flex-wrap gap-2">
        {pkg.actions.map((action) => (
          <Button
            key={action.id}
            variant={action.destructive ? "danger" : "default"}
            disabled={busy}
            onClick={() => (action.destructive ? setConfirming(action) : start(action))}
          >
            {action.label}
          </Button>
        ))}
      </div>

      {running && (
        <div className="flex flex-col gap-2 rounded-lg border border-line bg-panel p-3">
          {running.message && (
            <p className="whitespace-pre-wrap break-words text-xs text-fg-soft">
              <Linkified text={running.message} />
            </p>
          )}
          {running.fields.map((field) => (
            <FieldRow
              key={field.key}
              field={field}
              draft={running.values}
              onChange={(value) =>
                setRunning((current) =>
                  current ? { ...current, values: { ...current.values, [field.key]: value } } : current,
                )
              }
            />
          ))}
          <div className="flex gap-2">
            <Button
              variant="primary"
              disabled={busy}
              onClick={() => void submit(running.action, running.values, running.state)}
            >
              {busy ? t("connections.action_running") : t("connections.action_continue")}
            </Button>
            <Button onClick={() => setRunning(null)} disabled={busy}>
              {t("common.cancel")}
            </Button>
          </div>
        </div>
      )}

      {result && (
        <p
          className={`whitespace-pre-wrap break-words rounded-lg px-3 py-2 text-xs ${
            result.ok
              ? "border border-ok/30 bg-ok/10 text-ok-text"
              : "border border-danger/30 bg-danger/10 text-danger-text"
          }`}
        >
          <Linkified text={result.message} />
        </p>
      )}

      <ConfirmDialog
        open={confirming !== null}
        title={confirming?.label ?? ""}
        description={confirming?.description ?? ""}
        confirmLabel={t("common.continue")}
        cancelLabel={t("common.cancel")}
        danger
        onConfirm={() => {
          const action = confirming;
          setConfirming(null);
          if (action) start(action);
        }}
        onCancel={() => setConfirming(null)}
      />
    </div>
  );
}

/** An action's message may carry a URL the user has to open -- an OAuth
 * consent link, typically. Only http(s) is linkified, and the text is
 * rendered as text either way; nothing here interprets markup. */
function Linkified({ text }: { text: string }) {
  const parts = text.split(/(https?:\/\/\S+)/g);
  return (
    <>
      {parts.map((part, index) =>
        /^https?:\/\//.test(part) ? (
          <a
            key={index}
            href={part}
            target="_blank"
            rel="noreferrer noopener"
            className="text-accent-text underline underline-offset-2"
          >
            {part}
          </a>
        ) : (
          <span key={index}>{part}</span>
        ),
      )}
    </>
  );
}

function ConnectionRow({
  label,
  ok,
  probe,
}: {
  label: string;
  ok: boolean;
  probe?: ProbeResult;
}) {
  const t = useT();
  return (
    <div className="flex items-center justify-between gap-2 rounded-lg border border-line bg-app px-3 py-2 text-sm">
      <span className="text-fg-soft">{label}</span>
      <div className="flex items-center gap-2">
        <Badge tone={ok ? "ok" : "bad"}>{ok ? t("common.configured") : t("connections.missing_short")}</Badge>
        {probe && (
          <Badge tone={probe.ok ? "ok" : "bad"}>{probe.ok ? t("connections.live") : t("connections.error_short")}</Badge>
        )}
      </div>
    </div>
  );
}
