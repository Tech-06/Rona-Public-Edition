import { useCallback, useState } from "react";
import { ApiError } from "../../api/client";
import { dashboardApi, type ArchiveReason, type MemoryLayer } from "../../api/dashboard";
import { usePoll } from "../../hooks/usePoll";
import type { TranslationKey } from "../../lib/i18n";
import { useLanguage, useT } from "../LanguageProvider";
import { ConfirmDialog } from "../ui/ConfirmDialog";
import { ArchiveIcon, RotateCcwIcon, Trash2Icon } from "../ui/icons";
import { Badge, Card, EmptyState, ErrorState, IconButton } from "./ui";

type Tab = "notes" | "people" | "memories" | "archive";

const TABS: Array<{ id: Tab; labelKey: TranslationKey }> = [
  { id: "notes", labelKey: "data.tab_notes" },
  { id: "people", labelKey: "data.tab_people" },
  { id: "memories", labelKey: "data.tab_memories" },
  { id: "archive", labelKey: "data.tab_archive" },
];

export function DataPanel() {
  const t = useT();
  const [tab, setTab] = useState<Tab>("notes");

  return (
    <div className="flex flex-col gap-4">
      <div className="flex gap-1.5">
        {TABS.map((item) => (
          <button
            key={item.id}
            type="button"
            onClick={() => setTab(item.id)}
            className={`rounded-full px-3 py-1.5 text-sm transition-colors ${
              tab === item.id
                ? "bg-accent text-accent-fg"
                : "border border-line text-fg-muted hover:text-fg-soft"
            }`}
          >
            {t(item.labelKey)}
          </button>
        ))}
      </div>
      {tab === "notes" && <NotesTab />}
      {tab === "people" && <PeopleTab />}
      {tab === "memories" && <MemoriesTab />}
      {tab === "archive" && <ArchiveTab />}
    </div>
  );
}

/** Shared row-action plumbing for every tab below: tracks which row's
 * request is in flight (so its buttons can disable) and surfaces a
 * thrown ApiError as a message an ErrorState can render, then refreshes
 * the list on success. */
function useRowActions(refresh: () => void) {
  const t = useT();
  const [busyId, setBusyId] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function run<T>(id: number, action: () => Promise<T>): Promise<T | undefined> {
    setBusyId(id);
    setError(null);
    try {
      const result = await action();
      refresh();
      return result;
    } catch (err) {
      setError(err instanceof ApiError ? err.message : t("common.action_failed"));
      return undefined;
    } finally {
      setBusyId(null);
    }
  }

  return { busyId, error, run };
}

function NotesTab() {
  const t = useT();
  const notes = usePoll(useCallback(() => dashboardApi.notes(), []), null);
  const { busyId, error, run } = useRowActions(notes.refresh);
  const [pendingDelete, setPendingDelete] = useState<{ id: number; title: string } | null>(null);

  if (notes.error) return <ErrorState message={notes.error} />;
  if (!notes.data) return null;
  if (!notes.data.installed) {
    return (
      <EmptyState>
        {t("data.notes_not_installed")}{" "}
        <code className="rounded bg-app px-1 py-0.5 text-xs">
          rona tools install notes
        </code>
      </EmptyState>
    );
  }

  async function confirmDelete() {
    if (!pendingDelete) return;
    const id = pendingDelete.id;
    setPendingDelete(null);
    await run(id, () => dashboardApi.deleteNote(id));
  }

  return (
    <div className="flex flex-col gap-2">
      {error && <ErrorState message={error} />}
      {notes.data.notes.length === 0 ? (
        <EmptyState>{t("data.no_notes")}</EmptyState>
      ) : (
        notes.data.notes.map((note) => {
          const id = Number(note.id);
          const title = String(note.title);
          return (
            <Card key={id}>
              <div className="flex items-start justify-between gap-3">
                <div className="min-w-0 break-words">
                  <p className="text-sm font-medium text-fg-soft">{title}</p>
                  <p className="mt-1 text-sm text-fg-muted">{String(note.body)}</p>
                  <p className="mt-1 text-xs text-fg-faint">{String(note.date)}</p>
                </div>
                <IconButton
                  label={t("common.delete")}
                  variant="danger"
                  disabled={busyId === id}
                  onClick={() => setPendingDelete({ id, title })}
                >
                  <Trash2Icon className="h-4 w-4" />
                </IconButton>
              </div>
            </Card>
          );
        })
      )}
      <ConfirmDialog
        open={pendingDelete !== null}
        title={t("data.delete_note_title")}
        description={
          pendingDelete ? t("data.delete_note_description", { title: pendingDelete.title }) : undefined
        }
        onCancel={() => setPendingDelete(null)}
        onConfirm={confirmDelete}
      />
    </div>
  );
}

function PeopleTab() {
  const t = useT();
  const people = usePoll(useCallback(() => dashboardApi.people(), []), null);
  const { busyId, error, run } = useRowActions(people.refresh);
  const [pendingDelete, setPendingDelete] = useState<{ id: number; name: string } | null>(null);
  const [archivedNote, setArchivedNote] = useState<number | null>(null);

  if (people.error) return <ErrorState message={people.error} />;
  if (!people.data) return null;

  async function confirmDelete() {
    if (!pendingDelete) return;
    const id = pendingDelete.id;
    setPendingDelete(null);
    setArchivedNote(null);
    const result = await run(id, () => dashboardApi.deletePerson(id));
    setArchivedNote(result && result.archived_memories > 0 ? result.archived_memories : null);
  }

  return (
    <div className="flex flex-col gap-2">
      {error && <ErrorState message={error} />}
      {archivedNote !== null && (
        <p className="rounded-lg border border-line bg-app px-3 py-2 text-xs text-fg-subtle">
          {t("data.person_deleted_archived", { count: archivedNote })}
        </p>
      )}
      {people.data.people.length === 0 ? (
        <EmptyState>{t("data.no_people")}</EmptyState>
      ) : (
        <div className="grid grid-cols-[repeat(auto-fit,minmax(240px,1fr))] gap-2">
          {people.data.people.map((person) => {
            const id = Number(person.id);
            const name = `${String(person.name)}${person.surname ? ` ${String(person.surname)}` : ""}`;
            return (
              <Card key={id}>
                <div className="flex items-start justify-between gap-3">
                  <div className="min-w-0 break-words">
                    <p className="text-sm font-medium text-fg-soft">{name}</p>
                    {person.connection ? (
                      <p className="text-xs text-fg-subtle">{String(person.connection)}</p>
                    ) : null}
                    {person.phone_num ? (
                      <p className="text-xs text-fg-subtle">{String(person.phone_num)}</p>
                    ) : null}
                    {person.mail ? <p className="text-xs text-fg-subtle">{String(person.mail)}</p> : null}
                  </div>
                  <IconButton
                    label={t("common.delete")}
                    variant="danger"
                    disabled={busyId === id}
                    onClick={() => setPendingDelete({ id, name })}
                  >
                    <Trash2Icon className="h-4 w-4" />
                  </IconButton>
                </div>
              </Card>
            );
          })}
        </div>
      )}
      <ConfirmDialog
        open={pendingDelete !== null}
        title={t("data.delete_person_title")}
        description={
          pendingDelete ? t("data.delete_person_description", { name: pendingDelete.name }) : undefined
        }
        onCancel={() => setPendingDelete(null)}
        onConfirm={confirmDelete}
      />
    </div>
  );
}

function layerTone(layer: MemoryLayer): "ok" | "warn" | "neutral" {
  if (layer === "deep") return "ok";
  if (layer === "seasonal") return "warn";
  return "neutral";
}

function MemoriesTab() {
  const t = useT();
  const { locale } = useLanguage();
  const memories = usePoll(useCallback(() => dashboardApi.memories(), []), null);
  const { busyId, error, run } = useRowActions(memories.refresh);
  const [pendingDelete, setPendingDelete] = useState<number | null>(null);

  function formatDate(value: string): string {
    return new Date(value).toLocaleString(locale === "tr" ? "tr-TR" : "en-US");
  }

  if (memories.error) return <ErrorState message={memories.error} />;
  if (!memories.data) return null;

  async function confirmDelete() {
    if (pendingDelete === null) return;
    const id = pendingDelete;
    setPendingDelete(null);
    await run(id, () => dashboardApi.deleteMemory(id));
  }

  return (
    <div className="flex flex-col gap-2">
      {error && <ErrorState message={error} />}
      {memories.data.memories.length === 0 ? (
        <EmptyState>{t("data.no_memories")}</EmptyState>
      ) : (
        memories.data.memories.map((memory) => (
          <Card key={memory.id}>
            <div className="flex items-start justify-between gap-3">
              <div className="min-w-0 break-words">
                <p className="text-sm text-fg-soft">{memory.content}</p>
                <div className="mt-1.5 flex flex-wrap items-center gap-2 text-xs text-fg-faint">
                  <Badge tone={layerTone(memory.layer)}>{memory.layer}</Badge>
                  <span>
                    {t("data.memory_hits", { hits: memory.layer_hits, total: memory.access_count })}
                  </span>
                  <span>
                    {memory.last_accessed
                      ? t("data.last_access", { date: formatDate(memory.last_accessed) })
                      : t("data.never_accessed")}
                  </span>
                  <span>{formatDate(memory.created_at)}</span>
                </div>
              </div>
              <div className="flex shrink-0 gap-1">
                <IconButton
                  label={t("data.action_archive")}
                  disabled={busyId === memory.id}
                  onClick={() => run(memory.id, () => dashboardApi.archiveMemory(memory.id))}
                >
                  <ArchiveIcon className="h-4 w-4" />
                </IconButton>
                <IconButton
                  label={t("common.delete")}
                  variant="danger"
                  disabled={busyId === memory.id}
                  onClick={() => setPendingDelete(memory.id)}
                >
                  <Trash2Icon className="h-4 w-4" />
                </IconButton>
              </div>
            </div>
          </Card>
        ))
      )}
      <ConfirmDialog
        open={pendingDelete !== null}
        title={t("data.delete_memory_title")}
        description={t("data.delete_memory_description")}
        onCancel={() => setPendingDelete(null)}
        onConfirm={confirmDelete}
      />
    </div>
  );
}

function archiveReasonKey(reason: ArchiveReason): TranslationKey {
  if (reason === "auto") return "data.archive_reason_auto";
  if (reason === "manual") return "data.archive_reason_manual";
  return "data.archive_reason_person_deleted";
}

function ArchiveTab() {
  const t = useT();
  const { locale } = useLanguage();
  const archive = usePoll(useCallback(() => dashboardApi.archive(), []), null);
  const { busyId, error, run } = useRowActions(archive.refresh);
  const [pendingDelete, setPendingDelete] = useState<number | null>(null);

  function formatDate(value: string): string {
    return new Date(value).toLocaleString(locale === "tr" ? "tr-TR" : "en-US");
  }

  if (archive.error) return <ErrorState message={archive.error} />;
  if (!archive.data) return null;

  async function confirmDelete() {
    if (pendingDelete === null) return;
    const id = pendingDelete;
    setPendingDelete(null);
    await run(id, () => dashboardApi.deleteArchived(id));
  }

  return (
    <div className="flex flex-col gap-2">
      {error && <ErrorState message={error} />}
      {archive.data.archive.length === 0 ? (
        <EmptyState>{t("data.no_archive")}</EmptyState>
      ) : (
        archive.data.archive.map((entry) => (
          <Card key={entry.id}>
            <div className="flex items-start justify-between gap-3">
              <div className="min-w-0 break-words">
                <p className="text-sm text-fg-soft">{entry.content}</p>
                <div className="mt-1.5 flex flex-wrap items-center gap-2 text-xs text-fg-faint">
                  <span>{t("data.previous_layer", { layer: entry.layer })}</span>
                  <span>{t(archiveReasonKey(entry.reason))}</span>
                  <span>{t("data.archived_at", { date: formatDate(entry.archived_at) })}</span>
                </div>
              </div>
              <div className="flex shrink-0 gap-1">
                <IconButton
                  label={t("data.action_restore")}
                  disabled={busyId === entry.id}
                  onClick={() => run(entry.id, () => dashboardApi.restoreArchived(entry.id))}
                >
                  <RotateCcwIcon className="h-4 w-4" />
                </IconButton>
                <IconButton
                  label={t("common.delete")}
                  variant="danger"
                  disabled={busyId === entry.id}
                  onClick={() => setPendingDelete(entry.id)}
                >
                  <Trash2Icon className="h-4 w-4" />
                </IconButton>
              </div>
            </div>
          </Card>
        ))
      )}
      <ConfirmDialog
        open={pendingDelete !== null}
        title={t("data.delete_archived_title")}
        description={t("data.delete_archived_description")}
        onCancel={() => setPendingDelete(null)}
        onConfirm={confirmDelete}
      />
    </div>
  );
}
