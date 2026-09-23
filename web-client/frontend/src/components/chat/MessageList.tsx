import { useEffect, useRef } from "react";
import type { ChatMessage } from "../../types";
import { useT } from "../LanguageProvider";
import { MessageBubble } from "./MessageBubble";

interface Props {
  messages: ChatMessage[];
  livePhase: string | null;
  /** True while an existing conversation's transcript is still being
   * fetched from the server (see useChat.ts) -- distinct from an empty
   * chat, which should show the "what's on your mind" prompt instead. */
  loading?: boolean;
}

export function MessageList({ messages, livePhase, loading }: Props) {
  const t = useT();
  const endRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [messages, livePhase]);

  if (loading) {
    return (
      <div className="flex h-full flex-col items-center justify-center gap-3 px-4 text-center text-sm text-fg-subtle">
        <span className="flex gap-1">
          <span className="h-1.5 w-1.5 rounded-full bg-fg-faint animate-pulseDot [animation-delay:-0.3s]" />
          <span className="h-1.5 w-1.5 rounded-full bg-fg-faint animate-pulseDot [animation-delay:-0.15s]" />
          <span className="h-1.5 w-1.5 rounded-full bg-fg-faint animate-pulseDot" />
        </span>
        <span>{t("common.loading")}</span>
      </div>
    );
  }

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
