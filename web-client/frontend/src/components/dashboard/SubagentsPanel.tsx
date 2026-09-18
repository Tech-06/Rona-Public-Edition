import { useCallback, useState } from "react";
import { dashboardApi } from "../../api/dashboard";
import { usePoll } from "../../hooks/usePoll";
import { Badge, Card, EmptyState, ErrorState } from "./ui";

function formatDate(value: string | null): string {
  if (!value) return "—";
  return new Date(value).toLocaleString("tr-TR");
}

const STATUS_TONE: Record<string, "ok" | "bad" | "neutral"> = {
  completed: "ok",
  failed: "bad",
  running: "neutral",
};

export function SubagentsPanel() {
  const subagents = usePoll(useCallback(() => dashboardApi.subagents(), []), 8000);
  const [expanded, setExpanded] = useState<string | null>(null);

  if (subagents.error) return <ErrorState message={subagents.error} />;
  if (!subagents.data) return null;

  if (subagents.data.runs.length === 0) {
    return <EmptyState>Arka plan ajan çalışması yok.</EmptyState>;
  }

  return (
    <div className="flex flex-col gap-3">
      {subagents.data.runs.map((run) => {
        const isExpanded = expanded === run.id;
        return (
          <Card key={run.id}>
            <button
              type="button"
              onClick={() => setExpanded(isExpanded ? null : run.id)}
              className="flex w-full items-start justify-between gap-3 text-left"
            >
              <div className="min-w-0">
                <p className="truncate text-sm text-fg-soft">{run.task}</p>
                <p className="mt-1 text-xs text-fg-subtle">
                  {run.tier} · {formatDate(run.created_at)}
                </p>
              </div>
              <Badge tone={STATUS_TONE[run.status] ?? "neutral"}>{run.status}</Badge>
            </button>
            {isExpanded && (
              <div className="mt-3 border-t border-line pt-3 text-xs text-fg-muted">
                {run.summary && <p className="mb-2">{run.summary}</p>}
                {run.report && <p className="whitespace-pre-wrap text-fg-subtle">{run.report}</p>}
                {run.error && <p className="text-danger-text">{run.error}</p>}
              </div>
            )}
          </Card>
        );
      })}
    </div>
  );
}
