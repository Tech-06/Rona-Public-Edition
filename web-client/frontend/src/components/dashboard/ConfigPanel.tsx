import { useCallback, useEffect, useState } from "react";
import { dashboardApi } from "../../api/dashboard";
import { usePoll } from "../../hooks/usePoll";
import { Button, Card, ErrorState } from "./ui";

const GROUPS: Array<{ title: string; fields: string[] }> = [
  { title: "Genel", fields: ["log_level", "reload"] },
  { title: "Model", fields: ["flash_model", "flash_model_url", "pro_model", "pro_model_url"] },
  {
    title: "Sohbet",
    fields: [
      "conversation_ttl_seconds",
      "max_history_messages",
      "llm_timeout_seconds",
      "graph_recursion_limit",
    ],
  },
  {
    title: "Arka plan ajanları",
    fields: [
      "subagent_max_rounds",
      "subagent_timeout_seconds",
      "subagent_max_concurrent",
      "subagent_retention_hours",
      "subagent_llm_timeout_seconds",
      "subagent_max_context_messages",
    ],
  },
  {
    title: "Zamanlanmış görevler",
    fields: [
      "trigger_timezone",
      "trigger_max_concurrent",
      "trigger_max_rounds",
      "trigger_llm_timeout_seconds",
      "trigger_max_context_messages",
    ],
  },
  {
    title: "Web arayüzü",
    fields: ["web_autostart", "web_client_dir"],
  },
];

type FieldValue = string | number | boolean;

export function ConfigPanel() {
  const config = usePoll(useCallback(() => dashboardApi.config(), []), null);
  const [draft, setDraft] = useState<Record<string, FieldValue>>({});
  const [dirty, setDirty] = useState<Set<string>>(new Set());
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [restartRequired, setRestartRequired] = useState(false);

  useEffect(() => {
    if (config.data) {
      setDraft(config.data.values as Record<string, FieldValue>);
      setDirty(new Set());
    }
  }, [config.data]);

  function setField(field: string, value: FieldValue) {
    setDraft((current) => ({ ...current, [field]: value }));
    setDirty((current) => new Set(current).add(field));
  }

  async function save() {
    if (dirty.size === 0) return;
    setSaving(true);
    setSaveError(null);
    const payload: Record<string, FieldValue> = {};
    for (const field of dirty) payload[field] = draft[field];
    try {
      const result = await dashboardApi.updateConfig(payload);
      setRestartRequired(result.restart_required);
      setDirty(new Set());
    } catch (err) {
      setSaveError(err instanceof Error ? err.message : "Kaydedilemedi");
    } finally {
      setSaving(false);
    }
  }

  async function restartNow() {
    await dashboardApi.serverAction("restart");
    setRestartRequired(false);
  }

  if (config.error) return <ErrorState message={config.error} />;
  if (!config.data) return null;

  const editable = new Set(config.data.editable);

  return (
    <div className="flex flex-col gap-4">
      {restartRequired && (
        <div className="flex items-center justify-between gap-3 rounded-xl border border-amber-500/40 bg-amber-500/10 px-4 py-3 text-sm text-amber-200">
          <span>Değişikliklerin uygulanması için sunucunun yeniden başlatılması gerekiyor.</span>
          <Button onClick={restartNow} variant="primary">
            Şimdi yeniden başlat
          </Button>
        </div>
      )}
      {saveError && <ErrorState message={saveError} />}

      {GROUPS.map((group) => (
        <Card key={group.title} title={group.title}>
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
            {group.fields.map((field) => (
              <FieldInput
                key={field}
                field={field}
                value={draft[field]}
                editable={editable.has(field)}
                onChange={(value) => setField(field, value)}
              />
            ))}
          </div>
        </Card>
      ))}

      <div className="flex items-center gap-3">
        <Button onClick={save} disabled={dirty.size === 0 || saving} variant="primary">
          {saving ? "Kaydediliyor..." : `Kaydet${dirty.size > 0 ? ` (${dirty.size})` : ""}`}
        </Button>
        {dirty.size > 0 && <span className="text-xs text-slate-500">Kaydedilmemiş değişiklik var</span>}
      </div>
    </div>
  );
}

function FieldInput({
  field,
  value,
  editable,
  onChange,
}: {
  field: string;
  value: FieldValue | undefined;
  editable: boolean;
  onChange: (value: FieldValue) => void;
}) {
  const label = field.replace(/_/g, " ");

  if (!editable) {
    return (
      <label className="flex flex-col gap-1">
        <span className="text-xs capitalize text-slate-500">{label}</span>
        <span className="rounded-lg border border-surface-border bg-surface px-2.5 py-1.5 text-sm text-slate-500">
          {String(value ?? "—")}
        </span>
      </label>
    );
  }

  if (typeof value === "boolean") {
    return (
      <label className="flex items-center justify-between gap-2 rounded-lg border border-surface-border bg-surface px-2.5 py-1.5">
        <span className="text-xs capitalize text-slate-400">{label}</span>
        <input
          type="checkbox"
          checked={value}
          onChange={(event) => onChange(event.target.checked)}
          className="h-4 w-4 accent-sky-500"
        />
      </label>
    );
  }

  if (typeof value === "number") {
    return (
      <label className="flex flex-col gap-1">
        <span className="text-xs capitalize text-slate-500">{label}</span>
        <input
          type="number"
          value={value}
          onChange={(event) => onChange(Number(event.target.value))}
          className="rounded-lg border border-surface-border bg-surface px-2.5 py-1.5 text-sm text-slate-100 focus:border-sky-500 focus:outline-none"
        />
      </label>
    );
  }

  return (
    <label className="flex flex-col gap-1">
      <span className="text-xs capitalize text-slate-500">{label}</span>
      <input
        type="text"
        value={String(value ?? "")}
        onChange={(event) => onChange(event.target.value)}
        className="rounded-lg border border-surface-border bg-surface px-2.5 py-1.5 text-sm text-slate-100 focus:border-sky-500 focus:outline-none"
      />
    </label>
  );
}
