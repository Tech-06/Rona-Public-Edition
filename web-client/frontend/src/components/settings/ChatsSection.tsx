import { useCallback, useEffect, useState } from "react";
import { dashboardApi } from "../../api/dashboard";
import { usePoll } from "../../hooks/usePoll";
import { clearAll, exportAll, notifyConversationsChanged } from "../../lib/storage";
import { useLanguage, useT } from "../LanguageProvider";
import { Button, Card, ErrorState } from "../dashboard/ui";
import { RestartBanner } from "./RestartBanner";

const CUSTOM_VALUE = "custom";

export function ChatsSection() {
  const t = useT();
  const { locale } = useLanguage();
  const config = usePoll(useCallback(() => dashboardApi.config(), []), null);
  const server = usePoll(useCallback(() => dashboardApi.serverStatus(), []), null);

  const TTL_PRESETS: Array<{ value: number; label: string }> = [
    { value: 0, label: t("chats.ttl_off") },
    { value: 3600, label: t("chats.ttl_1h") },
    { value: 7200, label: t("chats.ttl_2h") },
    { value: 21600, label: t("chats.ttl_6h") },
    { value: 86400, label: t("chats.ttl_1d") },
    { value: 604800, label: t("chats.ttl_7d") },
    { value: 2592000, label: t("chats.ttl_30d") },
  ];
  const DELETE_ALL_CONFIRM_WORD = t("chats.delete_confirm_word");

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
    // eslint-disable-next-line react-hooks/exhaustive-deps
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
        setSaveError(t("chats.invalid_ttl"));
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
      setSaveError(err instanceof Error ? err.message : t("common.save_failed"));
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

  async function handleExport() {
    setExportError(null);
    try {
      const data = await exportAll();
      const blob = new Blob([JSON.stringify(data, null, 2)], { type: "application/json" });
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      const stamp = new Date().toISOString().slice(0, 19).replace(/[:T]/g, "-");
      link.href = url;
      link.download = `${t("chats.export_filename_prefix")}-${stamp}.json`;
      document.body.appendChild(link);
      link.click();
      link.remove();
      URL.revokeObjectURL(url);
    } catch (err) {
      setExportError(err instanceof Error ? err.message : t("chats.export_failed"));
    }
  }

  async function handleDeleteAll() {
    // toLocaleUpperCase (not the locale-independent toUpperCase) so the
    // Turkish confirm word's dotted İ compares correctly against a
    // lowercase "i" typed on a Turkish keyboard.
    if (deleteConfirmText.trim().toLocaleUpperCase(locale) !== DELETE_ALL_CONFIRM_WORD) return;
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
      serverFailed ? t("chats.delete_partial_failure") : t("chats.delete_all_success"),
    );
  }

  const canAutoRestart = Boolean(
    server.data && (server.data.tracked_process_alive || server.data.systemctl_available),
  );

  const deleteConfirmMatches =
    deleteConfirmText.trim().toLocaleUpperCase(locale) === DELETE_ALL_CONFIRM_WORD;

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

      <Card title={t("chats.retention_title")}>
        <p className="mb-3 text-xs text-fg-subtle">{t("chats.retention_description")}</p>
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
            {t("chats.ttl_custom")}
          </button>
        </div>
        {ttlSelection === CUSTOM_VALUE && (
          <div className="mt-3 flex items-center gap-2">
            <input
              type="number"
              min={0}
              value={ttlCustomValue}
              onChange={(event) => handleTtlCustomChange(event.target.value)}
              placeholder={t("chats.seconds_placeholder")}
              className="w-32 rounded-lg border border-line bg-app px-2.5 py-1.5 text-sm text-fg focus:border-accent focus:outline-none"
            />
            <span className="text-xs text-fg-subtle">{t("chats.seconds_hint")}</span>
          </div>
        )}
      </Card>

      <Card title={t("chats.context_limit_title")}>
        <p className="mb-3 text-xs text-fg-subtle">{t("chats.context_limit_description")}</p>
        <div className="flex items-center gap-2">
          <input
            type="number"
            min={0}
            value={maxHistory}
            onChange={(event) => handleMaxHistoryChange(Number(event.target.value))}
            className="w-32 rounded-lg border border-line bg-app px-2.5 py-1.5 text-sm text-fg focus:border-accent focus:outline-none"
          />
          <span className="text-xs text-fg-subtle">{t("chats.messages_hint")}</span>
        </div>
      </Card>

      <div className="flex items-center gap-3">
        <Button onClick={save} disabled={dirty.size === 0 || saving} variant="primary">
          {saving ? t("common.saving") : `${t("chats.save")}${dirty.size > 0 ? ` (${dirty.size})` : ""}`}
        </Button>
        {dirty.size > 0 && (
          <span className="text-xs text-fg-subtle">{t("chats.unsaved_changes")}</span>
        )}
      </div>

      <Card title={t("chats.data_title")}>
        {exportError && <ErrorState message={exportError} />}
        {deleteError && <ErrorState message={deleteError} />}
        {deleteNotice && <p className="text-xs text-fg-muted">{deleteNotice}</p>}
        <div className="flex flex-wrap gap-2">
          <Button onClick={handleExport}>{t("chats.export_button")}</Button>
          <Button onClick={() => setDeleteConfirmOpen((value) => !value)} variant="danger">
            {t("chats.delete_all_button")}
          </Button>
        </div>
        {deleteConfirmOpen && (
          <div className="mt-3 flex flex-col gap-2 rounded-lg border border-danger/30 bg-danger/10 p-3">
            <p className="text-xs text-danger-text">
              {t("chats.delete_confirm_instruction", { word: DELETE_ALL_CONFIRM_WORD })}
            </p>
            <div className="flex items-center gap-2">
              <input
                type="text"
                value={deleteConfirmText}
                onChange={(event) => setDeleteConfirmText(event.target.value)}
                placeholder={DELETE_ALL_CONFIRM_WORD}
                className="w-32 rounded-lg border border-danger/40 bg-app px-2.5 py-1.5 text-sm text-fg focus:border-danger focus:outline-none"
              />
              <Button onClick={handleDeleteAll} variant="danger" disabled={deleting || !deleteConfirmMatches}>
                {deleting ? t("chats.deleting") : t("chats.confirm_and_delete")}
              </Button>
            </div>
          </div>
        )}
      </Card>
    </div>
  );
}
