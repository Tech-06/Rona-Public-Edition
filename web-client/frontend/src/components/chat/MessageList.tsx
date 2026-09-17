import { useEffect, useRef } from "react";
import type { ChatMessage } from "../../types";
import { MessageBubble } from "./MessageBubble";

interface Props {
  messages: ChatMessage[];
  livePhase: string | null;
}

export function MessageList({ messages, livePhase }: Props) {
  const endRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [messages, livePhase]);

  if (messages.length === 0) {
    return (
      <div className="flex h-full items-center justify-center text-slate-500">
        <p>Rona'ya bir şey sor.</p>
      </div>
    );
  }

  return (
    <div className="mx-auto flex w-full max-w-3xl flex-col gap-4 px-4 py-6">
      {messages.map((message) => (
        <MessageBubble
          key={message.id}
          message={message}
          livePhase={message.pending ? livePhase : undefined}
        />
      ))}
      <div ref={endRef} />
    </div>
  );
}
