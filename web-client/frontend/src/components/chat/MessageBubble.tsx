import { renderMarkdown } from "../../lib/markdown";
import type { ChatMessage, ToolCallInfo } from "../../types";
import { ProgressIndicator } from "./ProgressIndicator";

interface Props {
  message: ChatMessage;
  livePhase?: string | null;
}

export function MessageBubble({ message, livePhase }: Props) {
  if (message.role === "user") {
    return (
      <div className="flex justify-end">
        <div className="max-w-[75%] whitespace-pre-wrap rounded-2xl rounded-br-sm bg-sky-600/90 px-4 py-2.5 text-[15px] text-white">
          {message.content}
        </div>
      </div>
    );
  }

  return (
    <div className="flex justify-start">
      <div className="flex max-w-[80%] flex-col gap-2 rounded-2xl rounded-bl-sm border border-surface-border bg-surface-raised px-4 py-3">
        {message.pending && (
          <ProgressIndicator phase={livePhase} steps={message.steps ?? []} live />
        )}
        {!message.pending && (
          <>
            {message.steps && message.steps.length > 0 && (
              <ProgressIndicator
                steps={message.steps}
                live={false}
                totalDurationMs={message.totalDurationMs}
              />
            )}
            {message.error ? (
              <p className="text-sm text-rose-400">{message.error}</p>
            ) : (
              <div
                className="prose-rona text-[15px] text-slate-100"
                dangerouslySetInnerHTML={{ __html: renderMarkdown(message.content) }}
              />
            )}
            {message.awaitingConfirmation && message.toolCalls && message.toolCalls.length > 0 && (
              <PendingToolStrip toolCalls={message.toolCalls} />
            )}
          </>
        )}
      </div>
    </div>
  );
}

function PendingToolStrip({ toolCalls }: { toolCalls: ToolCallInfo[] }) {
  return (
    <div className="flex flex-col gap-1.5 rounded-lg border border-amber-500/30 bg-amber-500/10 px-3 py-2">
      {toolCalls.map((call, index) => (
        <div key={index} className="text-xs text-amber-200">
          <span className="font-semibold">{call.name}</span>
          {Object.keys(call.args).length > 0 && (
            <span className="text-amber-300/80"> · {JSON.stringify(call.args)}</span>
          )}
        </div>
      ))}
    </div>
  );
}
