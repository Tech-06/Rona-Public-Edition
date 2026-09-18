import { useCallback, useEffect, useState } from "react";
import { dashboardApi } from "../../api/dashboard";
import { usePoll } from "../../hooks/usePoll";
import { clearAll, exportAll, notifyConversationsChanged } from "../../lib/storage";
import { Button, Card, ErrorState } from "../dashboard/ui";
import { RestartBanner } from "./RestartBanner";

const TTL_PRESETS: Array<{ value: number; label: string }> = [
  { value: 0, label: "Kapalı" },
  { value: 3600, label: "1 saat" },
  { value: 7200, label: "2 saat" },
  { value: 21600, label: "6 saat" },
  { value: 86400, label: "1 gün" },
  { value: 604800, label: "7 gün" },
  { value: 2592000, label: "30 gün" },
];
const CUSTOM_VALUE = "custom";
const DELETE_ALL_CONFIRM_WORD = "SİL";

export function ChatsSection() {
  const config = usePoll(useCallback(() => dashboardApi.config(), []), null);
  const server = usePoll(useCallback(() => dashboardApi.serverStatus(), []), null);

  const [ttlSelection, setTtlSelection] = useState<string>(String(TTL_PRESETS[0].value));
  const [ttlCustomValue, setTtlCustomValue] = useState("");
  const [maxHistory, setMaxHistory] = useState(0);
  const [dirty, setDirty] = useState<Set<"conversation_ttl_seconds" | "max_history_messages">>(
    new Set(),
  );

  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [restartRequired, setRestartRequired] = useState(false);
  const [restarting, setRestarting] = useState(false);

  const [exportError, setExportError] = useState<string | null>(null);
  const [deleteConfirmOpen, setDeleteConfirmOpen] = useState(false);
  const [deleteConfirmText, setDeleteConfirmText] = useState("");
  const [deleting, setDeleting] = useState(false);
  const [deleteError, setDeleteError] = useState<string | null>(null);
  const [deleteNotice, setDeleteNotice] = useState<string | null>(null);

  useEffect(() => {
    if (!config.data) return;
    const values = config.data.values as Record<string, unknown>;
    const ttl = Number(values.conversation_ttl_seconds ?? 0);
    const preset = TTL_PRESETS.find((option) => option.value === ttl);
    if (preset) {
      setTtlSelection(String(preset.value));
    } else {
      setTtlSelection(CUSTOM_VALUE);
      setTtlCustomValue(String(ttl));
    }
    setMaxHistory(Number(values.max_history_messages ?? 0));
    setDirty(new Set());
  }, [config.data]);

  function markDirty(field: "conversation_ttl_seconds" | "max_history_messages") {
    setDirty((current) => new Set(current).add(field));
  }

  function handleTtlSelect(value: string) {
    setTtlSelection(value);
    markDirty("conversation_ttl_seconds");
  }

  function handleTtlCustomChange(value: string) {
    setTtlCustomValue(value);
    markDirty("conversation_ttl_seconds");
  }

  function handleMaxHistoryChange(value: number) {
    setMaxHistory(value);
    markDirty("max_history_messages");
  }

  function resolvedTtlSeconds(): number | null {
    if (ttlSelection !== CUSTOM_VALUE) return Number(ttlSelection);
    const parsed = Number(ttlCustomValue);
    return Number.isFinite(parsed) && parsed >= 0 ? Math.floor(parsed) : null;
  }

  async function save() {
    if (dirty.size === 0) return;
    const payload: Record<string, number> = {};
    if (dirty.has("conversation_ttl_seconds")) {
      const ttl = resolvedTtlSeconds();
      if (ttl === null) {
        setSaveError("Geçersiz süre değeri");
        return;
      }
      payload.conversation_ttl_seconds = ttl;
    }
    if (dirty.has("max_history_messages")) {
      payload.max_history_messages = maxHistory;
    }
    setSaving(true);
    setSaveError(null);
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
    setRestarting(true);
    try {
      await dashboardApi.serverAction("restart");
      setRestartRequired(false);
    } finally {
      setRestarting(false);
      server.refresh();
    }
  }

  function handleExport() {
    setExportError(null);
    try {
      const data = exportAll();
      const blob = new Blob([JSON.stringify(data, null, 2)], { type: "application/json" });
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      const stamp = new Date().toISOString().slice(0, 19).replace(/[:T]/g, "-");
      link.href = url;
      link.download = `rona-sohbetler-${stamp}.json`;
      document.body.appendChild(link);
      link.click();
      link.remove();
      URL.revokeObjectURL(url);
    } catch (err) {
      setExportError(err instanceof Error ? err.message : "Dışa aktarılamadı");
    }
  }

  async function handleDeleteAll() {
    if (deleteConfirmText.trim().toUpperCase() !== DELETE_ALL_CONFIRM_WORD) return;
    setDeleting(true);
    setDeleteError(null);
    setDeleteNotice(null);
    let serverFailed = false;
    try {
      await dashboardApi.deleteAllServerConversations();
    } catch {
      serverFailed = true;
    }
    clearAll();
    notifyConversationsChanged();
    setDeleting(false);
    setDeleteConfirmOpen(false);
    setDeleteConfirmText("");
    setDeleteNotice(
      serverFailed
        ? "Tarayıcıdaki sohbetler silindi. Sunucudaki geçmiş silinemedi (backend'e ulaşılamadı) — backend açıkken tekrar dene."
        : "Tüm sohbetler tarayıcından ve sunucudan silindi.",
    );
  }

  const canAutoRestart = Boolean(
    server.data && (server.data.tracked_process_alive || server.data.systemctl_available),
  );

  return (
    <div className="flex flex-col gap-4">
      <RestartBanner
        visible={restartRequired}
        onRestart={restartNow}
        canAutoRestart={canAutoRestart}
        restarting={restarting}
      />
      {config.error && <ErrorState message={config.error} />}
      {saveError && <ErrorState message={saveError} />}

      <Card title="Geçmiş saklama süresi">
        <p className="mb-3 text-xs text-fg-subtle">
          Bir süre sonra boşta kalan sohbetler sunucudan kalıcı olarak silinir. Sabitlenen
          sohbetler bu süreden muaftır. Varsayılan: kapalı (hiç silinmez).
        </p>
        <div className="flex flex-wrap gap-1.5">
          {TTL_PRESETS.map((option) => (
            <button
              key={option.value}
              type="button"
              onClick={() => handleTtlSelect(String(option.value))}
              className={`rounded-full border px-3 py-1.5 text-xs font-medium transition-colors ${
                ttlSelection === String(option.value)
                  ? "border-accent bg-accent/10 text-accent-text"
                  : "border-line text-fg-muted hover:bg-elevated hover:text-fg-soft"
              }`}
            >
              {option.label}
            </button>
          ))}
          <button
            type="button"
            onClick={() => handleTtlSelect(CUSTOM_VALUE)}
            className={`rounded-full border px-3 py-1.5 text-xs font-medium transition-colors ${
              ttlSelection === CUSTOM_VALUE
                ? "border-accent bg-accent/10 text-accent-text"
                : "border-line text-fg-muted hover:bg-elevated hover:text-fg-soft"
            }`}
          >
            Özel…
          </button>
        </div>
        {ttlSelection === CUSTOM_VALUE && (
          <div className="mt-3 flex items-center gap-2">
            <input
              type="number"
              min={0}
              value={ttlCustomValue}
              onChange={(event) => handleTtlCustomChange(event.target.value)}
              placeholder="saniye"
              className="w-32 rounded-lg border border-line bg-app px-2.5 py-1.5 text-sm text-fg focus:border-accent focus:outline-none"
            />
            <span className="text-xs text-fg-subtle">saniye (0 = kapalı)</span>
          </div>
        )}
      </Card>

      <Card title="Model bağlam sınırı">
        <p className="mb-3 text-xs text-fg-subtle">
          Bu sınır sohbetin kalıcı geçmişini budar ve saklama süresinden bağımsız çalışır. 0
          yaparsan budama yapılmaz — token maliyeti ve zaman aşımı riski artar.
        </p>
        <div className="flex items-center gap-2">
          <input
            type="number"
            min={0}
            value={maxHistory}
            onChange={(event) => handleMaxHistoryChange(Number(event.target.value))}
            className="w-32 rounded-lg border border-line bg-app px-2.5 py-1.5 text-sm text-fg focus:border-accent focus:outline-none"
          />
          <span className="text-xs text-fg-subtle">mesaj (0 = sınırsız)</span>
        </div>
      </Card>

      <div className="flex items-center gap-3">
        <Button onClick={save} disabled={dirty.size === 0 || saving} variant="primary">
          {saving ? "Kaydediliyor..." : `Kaydet${dirty.size > 0 ? ` (${dirty.size})` : ""}`}
        </Button>
        {dirty.size > 0 && <span className="text-xs text-fg-subtle">Kaydedilmemiş değişiklik var</span>}
      </div>

      <Card title="Veri">
        {exportError && <ErrorState message={exportError} />}
        {deleteError && <ErrorState message={deleteError} />}
        {deleteNotice && <p className="text-xs text-fg-muted">{deleteNotice}</p>}
        <div className="flex flex-wrap gap-2">
          <Button onClick={handleExport}>Tüm sohbetleri dışa aktar (JSON)</Button>
          <Button onClick={() => setDeleteConfirmOpen((value) => !value)} variant="danger">
            Tüm sohbetleri sil
          </Button>
        </div>
        {deleteConfirmOpen && (
          <div className="mt-3 flex flex-col gap-2 rounded-lg border border-danger/30 bg-danger/10 p-3">
            <p className="text-xs text-danger-text">
              Bu işlem tarayıcıdaki ve sunucudaki tüm sohbetleri kalıcı olarak siler (sabitlenmiş
              olanlar dahil) ve geri alınamaz. Onaylamak için "{DELETE_ALL_CONFIRM_WORD}" yaz.
            </p>
            <div className="flex items-center gap-2">
              <input
                type="text"
                value={deleteConfirmText}
                onChange={(event) => setDeleteConfirmText(event.target.value)}
                placeholder={DELETE_ALL_CONFIRM_WORD}
                className="w-32 rounded-lg border border-danger/40 bg-app px-2.5 py-1.5 text-sm text-fg focus:border-danger focus:outline-none"
              />
              <Button
                onClick={handleDeleteAll}
                variant="danger"
                disabled={deleting || deleteConfirmText.trim().toUpperCase() !== DELETE_ALL_CONFIRM_WORD}
              >
                {deleting ? "Siliniyor..." : "Onayla ve sil"}
              </Button>
            </div>
          </div>
        )}
      </Card>
    </div>
  );
}
