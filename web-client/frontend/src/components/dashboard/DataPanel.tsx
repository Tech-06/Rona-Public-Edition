import { useCallback, useState } from "react";
import { dashboardApi } from "../../api/dashboard";
import { usePoll } from "../../hooks/usePoll";
import { Card, EmptyState, ErrorState } from "./ui";

type Tab = "notes" | "people" | "memories";

const TABS: Array<{ id: Tab; label: string }> = [
  { id: "notes", label: "Notlar" },
  { id: "people", label: "Kişiler" },
  { id: "memories", label: "Hafıza" },
];

export function DataPanel() {
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
                ? "bg-sky-600 text-white"
                : "border border-surface-border text-slate-400 hover:text-slate-200"
            }`}
          >
            {item.label}
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
  const notes = usePoll(useCallback(() => dashboardApi.notes(), []), null);
  if (notes.error) return <ErrorState message={notes.error} />;
  if (!notes.data) return null;
  if (notes.data.notes.length === 0) return <EmptyState>Not yok.</EmptyState>;
  return (
    <div className="flex flex-col gap-2">
      {notes.data.notes.map((note) => (
        <Card key={String(note.id)}>
          <p className="text-sm font-medium text-slate-200">{String(note.title)}</p>
          <p className="mt-1 text-sm text-slate-400">{String(note.body)}</p>
          <p className="mt-1 text-xs text-slate-600">{String(note.date)}</p>
        </Card>
      ))}
    </div>
  );
}

function PeopleTab() {
  const people = usePoll(useCallback(() => dashboardApi.people(), []), null);
  if (people.error) return <ErrorState message={people.error} />;
  if (!people.data) return null;
  if (people.data.people.length === 0) return <EmptyState>Kişi yok.</EmptyState>;
  return (
    <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
      {people.data.people.map((person) => (
        <Card key={String(person.id)}>
          <p className="text-sm font-medium text-slate-200">
            {String(person.name)} {person.surname ? String(person.surname) : ""}
          </p>
          {person.connection ? (
            <p className="text-xs text-slate-500">{String(person.connection)}</p>
          ) : null}
          {person.phone_num ? <p className="text-xs text-slate-500">{String(person.phone_num)}</p> : null}
          {person.mail ? <p className="text-xs text-slate-500">{String(person.mail)}</p> : null}
        </Card>
      ))}
    </div>
  );
}

function MemoriesTab() {
  const memories = usePoll(useCallback(() => dashboardApi.memories(), []), null);
  if (memories.error) return <ErrorState message={memories.error} />;
  if (!memories.data) return null;
  if (memories.data.memories.length === 0) return <EmptyState>Hafıza kaydı yok.</EmptyState>;
  return (
    <div className="flex flex-col gap-2">
      {memories.data.memories.map((memory) => (
        <Card key={String(memory.id)}>
          <p className="text-sm text-slate-200">{String(memory.content)}</p>
          <p className="mt-1 text-xs text-slate-600">{String(memory.created_at)}</p>
        </Card>
      ))}
    </div>
  );
}
