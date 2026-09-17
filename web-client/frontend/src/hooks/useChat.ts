import { useCallback, useRef, useState } from "react";
import { streamChat } from "../api/sse";
import { loadMessages, saveConversation } from "../lib/storage";
import { agentPhaseLabel, confirmPhaseLabel, toolLabel } from "../lib/toolLabels";
import type { ChatMessage, ProgressEvent, StepRecord } from "../types";

function makeId(): string {
  return `${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
}

export function useChat(initialConversationId: string | null, onConversationId?: (id: string) => void) {
  const [conversationId, setConversationId] = useState<string | null>(initialConversationId);
  const [messages, setMessages] = useState<ChatMessage[]>(() =>
    initialConversationId ? loadMessages(initialConversationId) : [],
  );
  const [sending, setSending] = useState(false);
  const [livePhase, setLivePhase] = useState<string | null>(null);
  const [awaitingConfirmation, setAwaitingConfirmation] = useState(false);
  const abortRef = useRef<AbortController | null>(null);
  const startedAtRef = useRef<number>(0);

  const send = useCallback(
    (text: string) => {
      if (sending || !text.trim()) return;
      const userMessage: ChatMessage = {
        id: makeId(),
        role: "user",
        content: text,
        createdAt: Date.now(),
      };
      const assistantId = makeId();
      const assistantMessage: ChatMessage = {
        id: assistantId,
        role: "assistant",
        content: "",
        createdAt: Date.now(),
        pending: true,
        steps: [],
      };

      setMessages((current) => [...current, userMessage, assistantMessage]);
      setAwaitingConfirmation(false);
      setSending(true);
      setLivePhase("Düşünülüyor");
      startedAtRef.current = Date.now();

      const controller = new AbortController();
      abortRef.current = controller;
      const steps: StepRecord[] = [];

      function updateAssistant(patch: Partial<ChatMessage>) {
        setMessages((current) =>
          current.map((message) =>
            message.id === assistantId ? { ...message, ...patch } : message,
          ),
        );
      }

      function handleProgress(event: ProgressEvent) {
        if (event.type === "agent_start") {
          setLivePhase(agentPhaseLabel(event));
        } else if (event.type === "confirm_start") {
          setLivePhase(confirmPhaseLabel());
        } else if (event.type === "tool_start" && event.call_id && event.name) {
          steps.push({
            callId: event.call_id,
            name: event.name,
            args: event.args ?? {},
            status: "running",
            durationMs: null,
          });
          setLivePhase(toolLabel(event.name, event.args));
          updateAssistant({ steps: [...steps] });
        } else if (event.type === "tool_end" && event.call_id) {
          const step = steps.find((entry) => entry.callId === event.call_id);
          if (step) {
            step.status = event.status ?? "ok";
            step.durationMs = event.duration_ms ?? null;
          }
          updateAssistant({ steps: [...steps] });
        }
      }

      streamChat(
        text,
        conversationId,
        {
          onConversationId: (id) => {
            setConversationId((current) => current ?? id);
          },
          onProgress: handleProgress,
          onDone: (result) => {
            const finalId = result.conversation_id;
            setConversationId(finalId);
            onConversationId?.(finalId);
            const totalDurationMs = Date.now() - startedAtRef.current;
            const finalized: ChatMessage = {
              ...assistantMessage,
              content: result.reply,
              pending: false,
              steps,
              totalDurationMs,
              awaitingConfirmation: result.status === "confirmation_required",
              toolCalls: result.tool_calls,
            };
            setMessages((current) => {
              const next = current.map((message) =>
                message.id === assistantId ? finalized : message,
              );
              const firstUser = next.find((message) => message.role === "user");
              saveConversation(finalId, firstUser ? firstUser.content.slice(0, 60) : "Yeni sohbet", next);
              return next;
            });
            setAwaitingConfirmation(result.status === "confirmation_required");
            setSending(false);
            setLivePhase(null);
          },
          onError: (detail) => {
            updateAssistant({ pending: false, error: detail });
            setSending(false);
            setLivePhase(null);
          },
        },
        controller.signal,
      );
    },
    [conversationId, onConversationId, sending],
  );

  const approve = useCallback(() => send("evet, onaylıyorum"), [send]);
  const reject = useCallback(() => send("hayır, iptal et"), [send]);

  const stop = useCallback(() => {
    abortRef.current?.abort();
  }, []);

  return {
    conversationId,
    messages,
    sending,
    livePhase,
    awaitingConfirmation,
    send,
    approve,
    reject,
    stop,
  };
}
