import { useCallback, useState } from "react";
import { dashboardApi, type TaskResponse, type TaskRunResponse } from "../../api/dashboard";
import { usePoll } from "../../hooks/usePoll";
import { useLanguage, useT } from "../LanguageProvider";
import { Badge, Button, Card, EmptyState, ErrorState } from "./ui";

export function TasksPanel() {
  const t = useT();
  const { locale } = useLanguage();
  const tasks = usePoll(useCallback(() => dashboardApi.tasks(), []), 10000);
  const [expanded, setExpanded] = useState<string | null>(null);
  const [runs, setRuns] = useState<TaskRunResponse[]>([]);
  const [runsLoading, setRunsLoading] = useState(false);

  function formatDate(value: string | null): string {
    if (!value) return "—";
    return new Date(value).toLocaleString(locale === "tr" ? "tr-TR" : "en-US");
  }

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
    if (!confirm(t("tasks.confirm_delete", { name: task.name }))) return;
    await dashboardApi.deleteTask(task.id);
    tasks.refresh();
  }

  if (tasks.error) return <ErrorState message={tasks.error} />;
  if (!tasks.data) return null;

  if (tasks.data.tasks.length === 0) {
    return <EmptyState>{t("tasks.no_tasks")}</EmptyState>;
  }

  return (
    <div className="flex flex-col gap-3">
      {tasks.data.tasks.map((task) => (
        <Card key={task.id}>
          <div className="flex items-start justify-between gap-3">
            <div className="min-w-0">
              <div className="flex items-center gap-2">
                <p className="truncate text-sm font-medium text-fg-soft">{task.name}</p>
                <Badge tone={task.status === "active" ? "ok" : "neutral"}>{task.status}</Badge>
              </div>
              <p className="mt-1 truncate text-xs text-fg-subtle">{task.description}</p>
              <p className="mt-1 text-xs text-fg-faint">
                {t("tasks.next_run_label", { value: task.next_run ? formatDate(task.next_run) : "—" })}
              </p>
            </div>
            <div className="flex shrink-0 gap-1.5">
              <Button onClick={() => toggleExpand(task)}>{t("tasks.history_button")}</Button>
              <Button onClick={() => toggleStatus(task)}>
                {task.status === "active" ? t("tasks.deactivate") : t("tasks.activate")}
              </Button>
              <Button onClick={() => remove(task)} variant="danger">
                {t("common.delete")}
              </Button>
            </div>
          </div>
          {expanded === task.id && (
            <div className="mt-3 border-t border-line pt-3">
              {runsLoading && <p className="text-xs text-fg-subtle">{t("common.loading")}</p>}
              {!runsLoading && runs.length === 0 && (
                <p className="text-xs text-fg-subtle">{t("tasks.no_runs_yet")}</p>
              )}
              <ul className="flex flex-col gap-2">
                {runs.map((run) => (
                  <li key={run.id} className="rounded-lg bg-app px-3 py-2 text-xs">
                    <div className="flex items-center gap-2">
                      <Badge tone={run.status === "completed" ? "ok" : run.status === "failed" ? "bad" : "neutral"}>
                        {run.status}
                      </Badge>
                      <span className="text-fg-subtle">{formatDate(run.started_at)}</span>
                    </div>
                    {run.summary && <p className="mt-1 text-fg-muted">{run.summary}</p>}
                    {run.error && <p className="mt-1 text-danger-text">{run.error}</p>}
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
