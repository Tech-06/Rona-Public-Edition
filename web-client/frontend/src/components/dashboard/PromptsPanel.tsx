import { useCallback, useEffect, useRef, useState } from "react";
import { ApiError } from "../../api/client";
import {
  promptsApi,
  type PromptDetail,
  type PromptGroup,
  type PromptPlaceholder,
  type PromptSummary,
} from "../../api/prompts";
import { usePoll } from "../../hooks/usePoll";
import type { TranslationKey } from "../../lib/i18n";
import { useLanguage, useT } from "../LanguageProvider";
import { ConfirmDialog } from "../ui/ConfirmDialog";
import { ChevronLeftIcon } from "../ui/icons";
import { Badge, Button, Card, ErrorState } from "./ui";

/** Display copy for each of the 9 editable prompt ids -- the backend only
 * ever hands back id/filename/group, the human-facing name and
 * description live here so they can be localized. */
const PROMPT_INFO: Record<string, { nameKey: TranslationKey; descriptionKey: TranslationKey }> = {
  persona: { nameKey: "prompts.name_persona", descriptionKey: "prompts.description_persona" },
  output_text: { nameKey: "prompts.name_output_text", descriptionKey: "prompts.description_output_text" },
  user: { nameKey: "prompts.name_user", descriptionKey: "prompts.description_user" },
  toolbox: { nameKey: "prompts.name_toolbox", descriptionKey: "prompts.description_toolbox" },
  memory: { nameKey: "prompts.name_memory", descriptionKey: "prompts.description_memory" },
  subagents: { nameKey: "prompts.name_subagents", descriptionKey: "prompts.description_subagents" },
  trigger: { nameKey: "prompts.name_trigger", descriptionKey: "prompts.description_trigger" },
  subagent_worker: {
    nameKey: "prompts.name_subagent_worker",
    descriptionKey: "prompts.description_subagent_worker",
  },
  trigger_worker: {
    nameKey: "prompts.name_trigger_worker",
    descriptionKey: "prompts.description_trigger_worker",
  },
};

const GROUP_ORDER: PromptGroup[] = ["main", "subagent", "trigger"];

const GROUP_LABELS: Record<PromptGroup, TranslationKey> = {
  main: "prompts.group_main",
  subagent: "prompts.group_subagent",
  trigger: "prompts.group_trigger",
};

function promptName(t: ReturnType<typeof useT>, id: string): string {
  const info = PROMPT_INFO[id];
  return info ? t(info.nameKey) : id;
}

function promptDescription(t: ReturnType<typeof useT>, id: string): string {
  const info = PROMPT_INFO[id];
  return info ? t(info.descriptionKey) : "";
}

// -- unsaved-draft persistence (sessionStorage) ------------------------------
//
// Written on every keystroke rather than on unmount, so a draft survives
// even when the settings modal is dismissed with Escape (SettingsModal
// owns that key and closes the whole modal -- this component never gets a
// chance to intercept it). Keyed by the server version the edit started
// from, so a draft that's gone stale (edited elsewhere since) is dropped
// instead of silently clobbering a newer default/override on restore.

const DRAFT_PREFIX = "rona:prompt-draft:";

interface StoredDraft {
  baseVersion: string;
  content: string;
}

function readDraft(id: string): StoredDraft | null {
  try {
    const raw = sessionStorage.getItem(DRAFT_PREFIX + id);
    if (!raw) return null;
    const parsed = JSON.parse(raw) as Partial<StoredDraft>;
    if (typeof parsed.baseVersion === "string" && typeof parsed.content === "string") {
      return { baseVersion: parsed.baseVersion, content: parsed.content };
    }
    return null;
  } catch {
    return null;
  }
}

function writeDraft(id: string, draft: StoredDraft): void {
  try {
    sessionStorage.setItem(DRAFT_PREFIX + id, JSON.stringify(draft));
  } catch {
    // storage unavailable (private mode, quota) -- draft just won't survive
  }
}

function clearDraft(id: string): void {
  try {
    sessionStorage.removeItem(DRAFT_PREFIX + id);
  } catch {
    // ignore
  }
}

export function PromptsPanel() {
  const list = usePoll(useCallback(() => promptsApi.list(), []), 20000);
  const [selectedId, setSelectedId] = useState<string | null>(null);

  if (list.error) return <ErrorState message={list.error} />;
  if (!list.data) return null;

  if (selectedId) {
    return (
      <PromptEditor
        // Remount on id change: each prompt gets a clean slate of local
        // state instead of an effect trying to reset a dozen fields.
        key={selectedId}
        id={selectedId}
        maxBytes={list.data.max_bytes}
        placeholders={list.data.placeholders}
        onBack={() => setSelectedId(null)}
        onChanged={list.refresh}
      />
    );
  }

  return <PromptList prompts={list.data.prompts} onSelect={setSelectedId} />;
}

function PromptList({
  prompts,
  onSelect,
}: {
  prompts: PromptSummary[];
  onSelect: (id: string) => void;
}) {
  const t = useT();
  const { locale } = useLanguage();

  function formatDate(value: string): string {
    return new Date(value).toLocaleString(locale === "tr" ? "tr-TR" : "en-US");
  }

  return (
    <div className="flex flex-col gap-4">
      {GROUP_ORDER.map((group) => {
        const items = prompts.filter((item) => item.group === group);
        if (items.length === 0) return null;
        return (
          <Card key={group} title={t(GROUP_LABELS[group])}>
            <div className="flex flex-col gap-2">
              {items.map((item) => (
                <button
                  key={item.id}
                  type="button"
                  onClick={() => onSelect(item.id)}
                  className="flex flex-wrap items-center gap-2 rounded-lg border border-line bg-app px-3 py-2 text-left text-sm transition-colors hover:bg-elevated"
                >
                  <div className="min-w-0 flex-1">
                    <p className="font-medium text-fg-soft">{promptName(t, item.id)}</p>
                    <p className="text-xs text-fg-subtle">{promptDescription(t, item.id)}</p>
                    {item.customized && item.updated_at && (
                      <p className="mt-0.5 text-xs text-fg-faint">
                        {t("prompts.updated_at", { date: formatDate(item.updated_at) })}
                      </p>
                    )}
                  </div>
                  <div className="flex shrink-0 flex-wrap items-center gap-1.5">
                    {item.customized && <Badge tone="neutral">{t("prompts.customized_badge")}</Badge>}
                    {item.default_changed && (
                      <Badge tone="warn">{t("prompts.default_changed_badge")}</Badge>
                    )}
                  </div>
                </button>
              ))}
            </div>
          </Card>
        );
      })}
    </div>
  );
}

interface PromptEditorProps {
  id: string;
  maxBytes: number;
  placeholders: PromptPlaceholder[];
  onBack: () => void;
  onChanged: () => void;
}

function PromptEditor({ id, maxBytes, placeholders, onBack, onChanged }: PromptEditorProps) {
  const t = useT();
  const [detail, setDetail] = useState<PromptDetail | null>(null);
  const [content, setContent] = useState("");
  const [baseVersion, setBaseVersion] = useState("");
  const [loadError, setLoadError] = useState<string | null>(null);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [conflict, setConflict] = useState(false);
  const [warnings, setWarnings] = useState<string[]>([]);
  const [restoredNotice, setRestoredNotice] = useState(false);
  const [showDefault, setShowDefault] = useState(false);
  const [confirmKind, setConfirmKind] = useState<"reset" | "discard" | null>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  const load = useCallback(async () => {
    setLoadError(null);
    try {
      const data = await promptsApi.get(id);
      setDetail(data);
      setBaseVersion(data.version);
      const draft = readDraft(id);
      if (draft && draft.baseVersion === data.version && draft.content !== data.content) {
        setContent(draft.content);
        setRestoredNotice(true);
      } else {
        setContent(data.content);
        if (draft) clearDraft(id);
      }
    } catch (err) {
      setLoadError(err instanceof ApiError ? err.message : t("common.action_failed"));
    }
  }, [id, t]);

  useEffect(() => {
    void load();
  }, [load]);

  const dirty = detail !== null && content !== detail.content;

  useEffect(() => {
    if (!dirty) return;
    function handleBeforeUnload(event: BeforeUnloadEvent) {
      event.preventDefault();
      event.returnValue = "";
    }
    window.addEventListener("beforeunload", handleBeforeUnload);
    return () => window.removeEventListener("beforeunload", handleBeforeUnload);
  }, [dirty]);

  function updateContent(next: string) {
    setContent(next);
    setConflict(false);
    if (detail && next === detail.content) {
      clearDraft(id);
    } else {
      writeDraft(id, { baseVersion, content: next });
    }
  }

  function insertPlaceholder(name: string) {
    const snippet = `{{${name}}}`;
    const el = textareaRef.current;
    if (!el) {
      updateContent(content + snippet);
      return;
    }
    const start = el.selectionStart ?? content.length;
    const end = el.selectionEnd ?? content.length;
    const next = content.slice(0, start) + snippet + content.slice(end);
    updateContent(next);
    requestAnimationFrame(() => {
      el.focus();
      const pos = start + snippet.length;
      el.setSelectionRange(pos, pos);
    });
  }

  async function save() {
    if (!dirty || saving) return;
    setSaving(true);
    setSaveError(null);
    setConflict(false);
    try {
      const result = await promptsApi.save(id, content, baseVersion);
      setDetail(result);
      setBaseVersion(result.version);
      setContent(result.content);
      setWarnings(result.warnings);
      clearDraft(id);
      onChanged();
    } catch (err) {
      if (err instanceof ApiError && err.status === 409) {
        setConflict(true);
      } else {
        setSaveError(err instanceof ApiError ? err.message : t("common.save_failed"));
      }
    } finally {
      setSaving(false);
    }
  }

  async function loadServerVersion() {
    try {
      const fresh = await promptsApi.get(id);
      // The user's own draft stays in the textarea untouched -- only the
      // "what the server has" side (default content, base version) moves.
      setDetail(fresh);
      setBaseVersion(fresh.version);
      setConflict(false);
      // Re-key the stored draft to the new base, or closing the modal now
      // would drop it on reopen as "stale".
      if (content !== fresh.content) writeDraft(id, { baseVersion: fresh.version, content });
      else clearDraft(id);
    } catch (err) {
      setSaveError(err instanceof ApiError ? err.message : t("common.action_failed"));
    }
  }

  async function confirmReset() {
    setConfirmKind(null);
    setSaving(true);
    setSaveError(null);
    try {
      const fresh = await promptsApi.reset(id);
      setDetail(fresh);
      setBaseVersion(fresh.version);
      setContent(fresh.content);
      setWarnings([]);
      setConflict(false);
      setRestoredNotice(false);
      clearDraft(id);
      onChanged();
    } catch (err) {
      setSaveError(err instanceof ApiError ? err.message : t("common.action_failed"));
    } finally {
      setSaving(false);
    }
  }

  function requestBack() {
    if (dirty) {
      setConfirmKind("discard");
      return;
    }
    onBack();
  }

  if (!detail) {
    return (
      <div className="flex flex-col gap-3">
        <BackLink onClick={onBack} label={t("prompts.back_to_list")} />
        {loadError ? (
          <ErrorState message={loadError} />
        ) : (
          <p className="text-sm text-fg-subtle">{t("common.loading")}</p>
        )}
      </div>
    );
  }

  const byteLength = new TextEncoder().encode(content).length;
  const overLimit = byteLength > maxBytes;
  const missingPlaceholders = detail.required_placeholders.filter(
    (name) => !content.includes(`{{${name}}}`),
  );

  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <BackLink onClick={requestBack} label={t("prompts.back_to_list")} />
        <div className="flex flex-wrap items-center gap-1.5">
          {detail.customized && <Badge tone="neutral">{t("prompts.customized_badge")}</Badge>}
          {detail.default_changed && <Badge tone="warn">{t("prompts.default_changed_badge")}</Badge>}
        </div>
      </div>

      <div>
        <h3 className="text-sm font-semibold text-fg-soft">{promptName(t, id)}</h3>
        <p className="text-xs text-fg-subtle">{promptDescription(t, id)}</p>
      </div>

      {restoredNotice && (
        <p className="rounded-lg border border-line bg-app px-3 py-2 text-xs text-fg-subtle">
          {t("prompts.draft_restored")}
        </p>
      )}

      {detail.group !== "main" && (
        <p className="rounded-lg border border-line bg-app px-3 py-2 text-xs text-fg-subtle">
          {t("prompts.worker_note")}
        </p>
      )}
      {id === "trigger_worker" && (
        <p className="rounded-lg border border-warn/40 bg-warn/10 px-3 py-2 text-xs text-warn-text">
          {t("prompts.trigger_worker_contract_note")}
        </p>
      )}

      <div className="flex flex-col gap-1.5">
        <label htmlFor="prompt-editor-textarea" className="text-xs font-medium text-fg-soft">
          {t("prompts.editor_label")}
        </label>
        <textarea
          id="prompt-editor-textarea"
          ref={textareaRef}
          value={content}
          onChange={(event) => updateContent(event.target.value)}
          spellCheck={false}
          className="h-[55vh] min-h-[240px] w-full resize-y rounded-xl border border-line bg-code p-3 font-mono text-xs text-fg-soft focus:border-accent focus:outline-none"
        />
        <div className="flex flex-wrap items-center justify-between gap-2 text-xs text-fg-faint">
          <span>{t("prompts.byte_count", { count: byteLength, max: maxBytes })}</span>
          {overLimit && <span className="text-danger-text">{t("prompts.over_limit")}</span>}
        </div>
      </div>

      {placeholders.length > 0 && (
        <div className="flex flex-col gap-1.5">
          <span className="text-xs font-medium text-fg-soft">{t("prompts.placeholders_title")}</span>
          <div className="flex flex-wrap gap-1.5">
            {placeholders.map((placeholder) => {
              const missing = missingPlaceholders.includes(placeholder.name);
              return (
                <button
                  key={placeholder.name}
                  type="button"
                  onClick={() => insertPlaceholder(placeholder.name)}
                  title={placeholder.value}
                  className={`rounded-full px-2.5 py-1 font-mono text-xs transition-colors ${
                    missing
                      ? "border border-danger/40 bg-danger/10 text-danger-text"
                      : "border border-line text-fg-muted hover:text-fg-soft"
                  }`}
                >
                  {`{{${placeholder.name}}}`}
                </button>
              );
            })}
          </div>
        </div>
      )}

      {warnings.length > 0 && (
        <div className="flex flex-col gap-1 rounded-lg border border-warn/40 bg-warn/10 px-3 py-2 text-xs text-warn-text">
          {warnings.map((warning, index) => (
            <p key={index}>{warning}</p>
          ))}
        </div>
      )}

      {conflict && (
        <div className="flex flex-wrap items-center justify-between gap-2 rounded-lg border border-danger/30 bg-danger/10 px-3 py-2 text-xs text-danger-text">
          <span>{t("prompts.conflict_message")}</span>
          <Button onClick={() => void loadServerVersion()}>{t("prompts.load_server_version")}</Button>
        </div>
      )}

      {saveError && <ErrorState message={saveError} />}

      <div className="flex flex-wrap items-center gap-2">
        <Button variant="primary" disabled={!dirty || saving || overLimit} onClick={() => void save()}>
          {saving ? t("common.saving") : t("common.save")}
        </Button>
        {detail.customized && (
          <Button variant="danger" disabled={saving} onClick={() => setConfirmKind("reset")}>
            {t("prompts.reset_to_default")}
          </Button>
        )}
        <Button disabled={saving} onClick={() => setShowDefault((value) => !value)}>
          {showDefault ? t("prompts.hide_default") : t("prompts.show_default")}
        </Button>
      </div>

      <p className="text-xs text-fg-faint">{t("prompts.effective_next_message")}</p>

      {showDefault && (
        <div className="flex flex-col gap-2">
          <pre className="max-h-72 overflow-y-auto whitespace-pre-wrap break-words rounded-xl border border-line bg-code p-3 font-mono text-xs text-fg-soft">
            {detail.default_content}
          </pre>
          <div>
            <Button onClick={() => updateContent(detail.default_content)}>
              {t("prompts.copy_default_to_editor")}
            </Button>
          </div>
        </div>
      )}

      <ConfirmDialog
        open={confirmKind !== null}
        title={confirmKind === "reset" ? t("prompts.confirm_reset_title") : t("prompts.confirm_discard_title")}
        description={
          confirmKind === "reset"
            ? t("prompts.confirm_reset_description")
            : t("prompts.confirm_discard_description")
        }
        confirmLabel={confirmKind === "reset" ? t("prompts.reset_to_default") : t("prompts.discard_and_back")}
        cancelLabel={t("common.cancel")}
        onConfirm={() => {
          if (confirmKind === "reset") {
            void confirmReset();
            return;
          }
          setConfirmKind(null);
          clearDraft(id);
          onBack();
        }}
        onCancel={() => setConfirmKind(null)}
      />
    </div>
  );
}

function BackLink({ onClick, label }: { onClick: () => void; label: string }) {
  return (
    <button
      type="button"
      onClick={onClick}
      className="flex items-center gap-1 text-sm text-fg-muted transition-colors hover:text-fg-soft"
    >
      <ChevronLeftIcon className="h-4 w-4" />
      {label}
    </button>
  );
}
