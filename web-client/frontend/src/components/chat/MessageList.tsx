import { useEffect, useRef } from "react";
import type { ChatMessage } from "../../types";
import { useT } from "../LanguageProvider";
import { MessageBubble } from "./MessageBubble";

interface Props {
  messages: ChatMessage[];
  livePhase: string | null;
}

export function MessageList({ messages, livePhase }: Props) {
  const t = useT();
  const endRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [messages, livePhase]);

  if (messages.length === 0) {
    return (
      <div className="flex h-full flex-col items-center justify-center gap-6 px-4 text-center">
        <p className="text-2xl font-semibold text-fg-soft sm:text-3xl">{t("messages.empty_prompt")}</p>
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
