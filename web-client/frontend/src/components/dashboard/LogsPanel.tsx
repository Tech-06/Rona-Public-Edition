import { useEffect, useRef, useState } from "react";
import { Card } from "./ui";

const MAX_LINES = 500;

export function LogsPanel() {
  const [lines, setLines] = useState<string[]>([]);
  const [level, setLevel] = useState("");
  const [query, setQuery] = useState("");
  const [connected, setConnected] = useState(false);
  const endRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const params = new URLSearchParams();
    if (level) params.set("level", level);
    if (query) params.set("q", query);
    const source = new EventSource(`/api/logs?${params.toString()}`);
    source.onopen = () => setConnected(true);
    source.onerror = () => setConnected(false);
    source.onmessage = (event) => {
      try {
        const line = JSON.parse(event.data) as string;
        setLines((current) => [...current.slice(-(MAX_LINES - 1)), line]);
      } catch {
        // ignore malformed line
      }
    };
    return () => source.close();
  }, [level, query]);

  useEffect(() => {
    endRef.current?.scrollIntoView({ block: "end" });
  }, [lines]);

  return (
    <div className="flex h-full flex-col gap-3">
      <Card>
        <div className="flex flex-wrap items-center gap-2">
          <select
            value={level}
            onChange={(event) => setLevel(event.target.value)}
            className="rounded-lg border border-surface-border bg-surface px-2.5 py-1.5 text-sm text-slate-200"
          >
            <option value="">Tüm seviyeler</option>
            <option value="INFO">INFO</option>
            <option value="WARNING">WARNING</option>
            <option value="ERROR">ERROR</option>
          </select>
          <input
            type="text"
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder="Ara..."
            className="flex-1 rounded-lg border border-surface-border bg-surface px-2.5 py-1.5 text-sm text-slate-200 focus:border-sky-500 focus:outline-none"
          />
          <span className={`h-2 w-2 rounded-full ${connected ? "bg-emerald-500" : "bg-slate-600"}`} />
        </div>
      </Card>
      <div className="flex-1 overflow-y-auto rounded-xl border border-surface-border bg-black/40 p-3 font-mono text-xs text-slate-300">
        {lines.length === 0 && <p className="text-slate-600">Henüz log yok.</p>}
        {lines.map((line, index) => (
          <div key={index} className="whitespace-pre-wrap break-all">
            {line}
          </div>
        ))}
        <div ref={endRef} />
      </div>
    </div>
  );
}
