import { useCallback, useState } from "react";
import { dashboardApi } from "../../api/dashboard";
import { usePoll } from "../../hooks/usePoll";
import type { TranslationKey } from "../../lib/i18n";
import { useT } from "../LanguageProvider";
import { Card, EmptyState, ErrorState } from "./ui";

type Tab = "notes" | "people" | "memories";

const TABS: Array<{ id: Tab; labelKey: TranslationKey }> = [
  { id: "notes", labelKey: "data.tab_notes" },
  { id: "people", labelKey: "data.tab_people" },
  { id: "memories", labelKey: "data.tab_memories" },
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
    </div>
  );
}

function NotesTab() {
  const t = useT();
  const notes = usePoll(useCallback(() => dashboardApi.notes(), []), null);
  if (notes.error) return <ErrorState message={notes.error} />;
  if (!notes.data) return null;
  if (!notes.data.installed) {
    return (
      <EmptyState>
        {t("data.notes_not_installed")}{" "}
        <code className="rounded bg-app px-1 py-0.5 text-xs">
          python -m toolbox.manager install notes
        </code>
      </EmptyState>
    );
  }
  if (notes.data.notes.length === 0) return <EmptyState>{t("data.no_notes")}</EmptyState>;
  return (
    <div className="flex flex-col gap-2">
      {notes.data.notes.map((note) => (
        <Card key={String(note.id)}>
          <p className="text-sm font-medium text-fg-soft">{String(note.title)}</p>
          <p className="mt-1 text-sm text-fg-muted">{String(note.body)}</p>
          <p className="mt-1 text-xs text-fg-faint">{String(note.date)}</p>
        </Card>
      ))}
    </div>
  );
}

function PeopleTab() {
  const t = useT();
  const people = usePoll(useCallback(() => dashboardApi.people(), []), null);
  if (people.error) return <ErrorState message={people.error} />;
  if (!people.data) return null;
  if (people.data.people.length === 0) return <EmptyState>{t("data.no_people")}</EmptyState>;
  return (
    <div className="grid grid-cols-[repeat(auto-fit,minmax(240px,1fr))] gap-2">
      {people.data.people.map((person) => (
        <Card key={String(person.id)}>
          <p className="text-sm font-medium text-fg-soft">
            {String(person.name)} {person.surname ? String(person.surname) : ""}
          </p>
          {person.connection ? (
            <p className="text-xs text-fg-subtle">{String(person.connection)}</p>
          ) : null}
          {person.phone_num ? <p className="text-xs text-fg-subtle">{String(person.phone_num)}</p> : null}
          {person.mail ? <p className="text-xs text-fg-subtle">{String(person.mail)}</p> : null}
        </Card>
      ))}
    </div>
  );
}

function MemoriesTab() {
  const t = useT();
  const memories = usePoll(useCallback(() => dashboardApi.memories(), []), null);
  if (memories.error) return <ErrorState message={memories.error} />;
  if (!memories.data) return null;
  if (memories.data.memories.length === 0) return <EmptyState>{t("data.no_memories")}</EmptyState>;
  return (
    <div className="flex flex-col gap-2">
      {memories.data.memories.map((memory) => (
        <Card key={String(memory.id)}>
          <p className="text-sm text-fg-soft">{String(memory.content)}</p>
          <p className="mt-1 text-xs text-fg-faint">{String(memory.created_at)}</p>
        </Card>
      ))}
    </div>
  );
}
