import { useCallback, useEffect, useState } from "react";
import {
  dashboardApi,
  type PackageAction,
  type PackageConfigField,
  type PackageStatus,
  type ProbeResponse,
  type ProbeResult,
} from "../../api/dashboard";
import { usePoll } from "../../hooks/usePoll";
import { useT } from "../LanguageProvider";
import { ConfirmDialog } from "../ui/ConfirmDialog";
import { Badge, Button, Card, EmptyState, ErrorState } from "./ui";

export function ConnectionsPanel() {
  const t = useT();
  const connections = usePoll(useCallback(() => dashboardApi.connections(), []), 15000);
  const [probe, setProbe] = useState<ProbeResponse | null>(null);
  const [probing, setProbing] = useState(false);
  const [probeError, setProbeError] = useState<string | null>(null);

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

  if (connections.error) return <ErrorState message={connections.error} />;
  if (!connections.data) return null;
  const data = connections.data;

  return (
    <div className="flex flex-col gap-4">
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
          <ConnectionRow label={t("connections.flash_model")} ok={data.flash_configured} probe={probe?.llm} />
          <ConnectionRow label={t("connections.pro_model")} ok={data.pro_configured} />
          <ConnectionRow label={t("connections.gemini_embedding")} ok={data.gemini_embedding_configured} />
          <ConnectionRow label="rona.db" ok={data.db_present} />
          <ConnectionRow label={t("connections.checkpoint_db")} ok={data.checkpoint_db_present} />
        </div>
      </Card>

      <Card title={t("connections.packages_title")}>
        {data.packages.length === 0 ? (
          <EmptyState>
            {t("connections.no_packages")}{" "}
            <code className="rounded bg-app px-1 py-0.5 text-xs">
              rona tools install &lt;{t("connections.package_id_placeholder")}&gt;
            </code>
          </EmptyState>
        ) : (
          <div className="flex flex-col gap-2">
            {data.packages.map((pkg) => (
              <PackageRow
                key={pkg.id}
                pkg={pkg}
                probe={probe?.packages[pkg.id]}
                onChanged={connections.refresh}
              />
            ))}
          </div>
        )}
      </Card>
    </div>
  );
}

function PackageRow({
  pkg,
  probe,
  onChanged,
}: {
  pkg: PackageStatus;
  probe?: ProbeResult;
  onChanged: () => void;
}) {
  const t = useT();
  const [open, setOpen] = useState(false);
  // Nothing to show for a package that needs neither configuring nor any
  // operator action -- most of them.
  const hasPanel = pkg.config_fields.length > 0 || pkg.actions.length > 0;

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
        {probe && (
          <Badge tone={probe.ok ? "ok" : "bad"}>{probe.ok ? t("connections.live") : probe.detail}</Badge>
        )}
        {hasPanel && (
          <Button onClick={() => setOpen((value) => !value)}>
            {open ? t("connections.close") : t("connections.configure")}
          </Button>
        )}
      </div>
      {open && hasPanel && <PackagePanel pkg={pkg} onChanged={onChanged} />}
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
