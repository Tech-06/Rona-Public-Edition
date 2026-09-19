import { useEffect, useRef, useState } from "react";
import { useT } from "../LanguageProvider";
import { Card } from "./ui";

const MAX_LINES = 500;

export function LogsPanel() {
  const t = useT();
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
            className="rounded-lg border border-line bg-app px-2.5 py-1.5 text-sm text-fg-soft"
          >
            <option value="">{t("logs.all_levels")}</option>
            <option value="INFO">INFO</option>
            <option value="WARNING">WARNING</option>
            <option value="ERROR">ERROR</option>
          </select>
          <input
            type="text"
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder={t("logs.search_placeholder")}
            className="flex-1 rounded-lg border border-line bg-app px-2.5 py-1.5 text-sm text-fg-soft focus:border-accent focus:outline-none"
          />
          <span className={`h-2 w-2 rounded-full ${connected ? "bg-ok-hover" : "bg-fg-faint"}`} />
        </div>
      </Card>
      <div className="flex-1 overflow-y-auto rounded-xl border border-line bg-code p-3 font-mono text-xs text-fg-soft">
        {lines.length === 0 && <p className="text-fg-faint">{t("logs.no_logs")}</p>}
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
