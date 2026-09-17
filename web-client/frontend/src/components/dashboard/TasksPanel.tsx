import { useCallback, useState } from "react";
import { dashboardApi, type TaskResponse, type TaskRunResponse } from "../../api/dashboard";
import { usePoll } from "../../hooks/usePoll";
import { Badge, Button, Card, EmptyState, ErrorState } from "./ui";

function formatDate(value: string | null): string {
  if (!value) return "—";
  return new Date(value).toLocaleString("tr-TR");
}

export function TasksPanel() {
  const tasks = usePoll(useCallback(() => dashboardApi.tasks(), []), 10000);
  const [expanded, setExpanded] = useState<string | null>(null);
  const [runs, setRuns] = useState<TaskRunResponse[]>([]);
  const [runsLoading, setRunsLoading] = useState(false);

  async function toggleExpand(task: TaskResponse) {
    if (expanded === task.id) {
      setExpanded(null);
      return;
    }
    setExpanded(task.id);
    setRunsLoading(true);
    try {
      const result = await dashboardApi.taskRuns(task.id);
      setRuns(result.runs);
    } finally {
      setRunsLoading(false);
    }
  }

  async function toggleStatus(task: TaskResponse) {
    await dashboardApi.setTaskStatus(task.id, task.status === "active" ? "passive" : "active");
    tasks.refresh();
  }

  async function remove(task: TaskResponse) {
    if (!confirm(`"${task.name}" görevini silmek istediğine emin misin?`)) return;
    await dashboardApi.deleteTask(task.id);
    tasks.refresh();
  }

  if (tasks.error) return <ErrorState message={tasks.error} />;
  if (!tasks.data) return null;

  if (tasks.data.tasks.length === 0) {
    return <EmptyState>Zamanlanmış görev yok.</EmptyState>;
  }

  return (
    <div className="flex flex-col gap-3">
      {tasks.data.tasks.map((task) => (
        <Card key={task.id}>
          <div className="flex items-start justify-between gap-3">
            <div className="min-w-0">
              <div className="flex items-center gap-2">
                <p className="truncate text-sm font-medium text-slate-200">{task.name}</p>
                <Badge tone={task.status === "active" ? "ok" : "neutral"}>{task.status}</Badge>
              </div>
              <p className="mt-1 truncate text-xs text-slate-500">{task.description}</p>
              <p className="mt-1 text-xs text-slate-600">
                Sonraki çalışma: {task.next_run ? formatDate(task.next_run) : "—"}
              </p>
            </div>
            <div className="flex shrink-0 gap-1.5">
              <Button onClick={() => toggleExpand(task)}>Geçmiş</Button>
              <Button onClick={() => toggleStatus(task)}>
                {task.status === "active" ? "Durdur" : "Etkinleştir"}
              </Button>
              <Button onClick={() => remove(task)} variant="danger">
                Sil
              </Button>
            </div>
          </div>
          {expanded === task.id && (
            <div className="mt-3 border-t border-surface-border pt-3">
              {runsLoading && <p className="text-xs text-slate-500">Yükleniyor...</p>}
              {!runsLoading && runs.length === 0 && (
                <p className="text-xs text-slate-500">Henüz çalışma kaydı yok.</p>
              )}
              <ul className="flex flex-col gap-2">
                {runs.map((run) => (
                  <li key={run.id} className="rounded-lg bg-surface px-3 py-2 text-xs">
                    <div className="flex items-center gap-2">
                      <Badge tone={run.status === "completed" ? "ok" : run.status === "failed" ? "bad" : "neutral"}>
                        {run.status}
                      </Badge>
                      <span className="text-slate-500">{formatDate(run.started_at)}</span>
                    </div>
                    {run.summary && <p className="mt-1 text-slate-400">{run.summary}</p>}
                    {run.error && <p className="mt-1 text-rose-400">{run.error}</p>}
                  </li>
                ))}
              </ul>
            </div>
          )}
        </Card>
      ))}
    </div>
  );
}
