import { useState } from "react";
import { toolLabel } from "../../lib/toolLabels";
import type { StepRecord } from "../../types";

const STATUS_DOT: Record<StepRecord["status"], string> = {
  running: "bg-sky-400 animate-pulseDot",
  ok: "bg-emerald-500",
  error: "bg-rose-500",
  rejected: "bg-amber-500",
  unknown_tool: "bg-rose-500",
  bad_args: "bg-rose-500",
};

function formatDuration(ms: number | null | undefined): string {
  if (ms === null || ms === undefined) return "";
  if (ms < 1000) return `${ms} ms`;
  return `${(ms / 1000).toFixed(1)} sn`;
}

interface Props {
  phase?: string | null;
  steps: StepRecord[];
  live: boolean;
  totalDurationMs?: number;
}

export function ProgressIndicator({ phase, steps, live, totalDurationMs }: Props) {
  const [expanded, setExpanded] = useState(false);

  if (live) {
    return (
      <div className="flex flex-col gap-2">
        <div className="flex items-center gap-2 text-sm">
          <span className="flex gap-1">
            <span className="h-1.5 w-1.5 rounded-full bg-sky-400 animate-pulseDot [animation-delay:-0.3s]" />
            <span className="h-1.5 w-1.5 rounded-full bg-sky-400 animate-pulseDot [animation-delay:-0.15s]" />
            <span className="h-1.5 w-1.5 rounded-full bg-sky-400 animate-pulseDot" />
          </span>
          <span className="shimmer-text font-medium">{phase ?? "Düşünülüyor"}</span>
        </div>
        {steps.length > 0 && <StepTimeline steps={steps} />}
      </div>
    );
  }

  if (steps.length === 0) return null;

  const durationLabel = formatDuration(totalDurationMs);

  return (
    <div>
      <button
        type="button"
        onClick={() => setExpanded((value) => !value)}
        className="inline-flex items-center gap-1.5 rounded-full border border-surface-border bg-surface px-2.5 py-1 text-xs text-slate-400 transition-colors hover:text-slate-200"
      >
        <span>
          {steps.length} adım{durationLabel ? ` · ${durationLabel}` : ""}
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
  return (
    <ul className="flex flex-col gap-1.5 border-l border-surface-border pl-3 text-xs text-slate-400">
      {steps.map((step) => (
        <li key={step.callId} className="flex items-center gap-2">
          <span className={`h-1.5 w-1.5 shrink-0 rounded-full ${STATUS_DOT[step.status]}`} />
          <span className="text-slate-300">{toolLabel(step.name, step.args)}</span>
          {step.durationMs !== null && (
            <span className="text-slate-500">{formatDuration(step.durationMs)}</span>
          )}
        </li>
      ))}
    </ul>
  );
}
