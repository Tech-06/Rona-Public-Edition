import { useState } from "react";
import { toolLabel } from "../../lib/toolLabels";
import type { StepRecord } from "../../types";
import { useT } from "../LanguageProvider";

const STATUS_DOT: Record<StepRecord["status"], string> = {
  running: "bg-accent-hover animate-pulseDot",
  ok: "bg-ok-hover",
  error: "bg-danger",
  rejected: "bg-warn",
  unknown_tool: "bg-danger",
  bad_args: "bg-danger",
};

function formatDuration(ms: number | null | undefined, t: ReturnType<typeof useT>): string {
  if (ms === null || ms === undefined) return "";
  if (ms < 1000) return `${ms} ms`;
  return t("progress.duration_seconds", { value: (ms / 1000).toFixed(1) });
}

interface Props {
  phase?: string | null;
  steps: StepRecord[];
  live: boolean;
  totalDurationMs?: number;
}

export function ProgressIndicator({ phase, steps, live, totalDurationMs }: Props) {
  const t = useT();
  const [expanded, setExpanded] = useState(false);

  if (live) {
    return (
      <div className="flex flex-col gap-2">
        <div className="flex items-center gap-2 text-sm">
          <span className="flex gap-1">
            <span className="h-1.5 w-1.5 rounded-full bg-accent-hover animate-pulseDot [animation-delay:-0.3s]" />
            <span className="h-1.5 w-1.5 rounded-full bg-accent-hover animate-pulseDot [animation-delay:-0.15s]" />
            <span className="h-1.5 w-1.5 rounded-full bg-accent-hover animate-pulseDot" />
          </span>
          <span className="shimmer-text font-medium">{phase ?? t("tool.thinking")}</span>
        </div>
        {steps.length > 0 && <StepTimeline steps={steps} />}
      </div>
    );
  }

  if (steps.length === 0) return null;

  const durationLabel = formatDuration(totalDurationMs, t);

  return (
    <div>
      <button
        type="button"
        onClick={() => setExpanded((value) => !value)}
        className="inline-flex items-center gap-1.5 rounded-full border border-line bg-app px-2.5 py-1 text-xs text-fg-muted transition-colors hover:text-fg-soft"
      >
        <span>
          {t("progress.steps_count", { count: steps.length })}
          {durationLabel ? ` · ${durationLabel}` : ""}
        </span>
        <span className={`transition-transform ${expanded ? "rotate-180" : ""}`}>⌄</span>
      </button>
      {expanded && (
        <div className="mt-2">
          <StepTimeline steps={steps} />
        </div>
      )}
    </div>
  );
}

function StepTimeline({ steps }: { steps: StepRecord[] }) {
  const t = useT();
  return (
    <ul className="flex flex-col gap-1.5 border-l border-line pl-3 text-xs text-fg-muted">
      {steps.map((step) => (
        <li key={step.callId} className="flex items-center gap-2">
          <span className={`h-1.5 w-1.5 shrink-0 rounded-full ${STATUS_DOT[step.status]}`} />
          <span className="text-fg-soft">{toolLabel(step.name, step.args)}</span>
          {step.durationMs !== null && (
            <span className="text-fg-subtle">{formatDuration(step.durationMs, t)}</span>
          )}
        </li>
      ))}
    </ul>
  );
}
