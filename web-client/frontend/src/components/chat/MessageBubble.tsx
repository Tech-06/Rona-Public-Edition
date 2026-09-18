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
        <div className="max-w-[85%] whitespace-pre-wrap rounded-2xl rounded-br-sm bg-accent/90 px-4 py-2.5 text-[15px] text-accent-fg sm:max-w-[75%]">
          {message.content}
        </div>
      </div>
    );
  }

  return (
    <div className="flex justify-start">
      <div className="flex max-w-[85%] flex-col gap-2 rounded-2xl rounded-bl-sm border border-line bg-panel px-4 py-3 sm:max-w-[80%]">
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
              <p className="text-sm text-danger-text">{message.error}</p>
            ) : (
              <div
                className="prose-rona text-[15px] text-fg"
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
    <div className="flex flex-col gap-1.5 rounded-lg border border-warn/30 bg-warn/10 px-3 py-2">
      {toolCalls.map((call, index) => (
        <div key={index} className="text-xs text-warn-strong">
          <span className="font-semibold">{call.name}</span>
          {Object.keys(call.args).length > 0 && (
            <span className="text-warn-text/80"> · {JSON.stringify(call.args)}</span>
          )}
        </div>
      ))}
    </div>
  );
}
