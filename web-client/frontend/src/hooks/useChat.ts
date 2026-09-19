import { useCallback, useRef, useState } from "react";
import { streamChat } from "../api/sse";
import { useT } from "../components/LanguageProvider";
import { loadMessages, saveConversation } from "../lib/storage";
import { agentPhaseLabel, confirmPhaseLabel, toolLabel } from "../lib/toolLabels";
import type { ChatMessage, ProgressEvent, StepRecord } from "../types";

function makeId(): string {
  return `${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
}

export function useChat(initialConversationId: string | null, onConversationId?: (id: string) => void) {
  const t = useT();
  const [conversationId, setConversationId] = useState<string | null>(initialConversationId);
  const [messages, setMessages] = useState<ChatMessage[]>(() =>
    initialConversationId ? loadMessages(initialConversationId) : [],
  );
  // Mirrors `messages` synchronously (unlike the state itself, which React
  // only applies once it gets around to processing the update). onDone
  // needs the up-to-date list *right now* to persist it before announcing
  // the conversation id to the sidebar - see onDone below.
  const messagesRef = useRef<ChatMessage[]>(messages);
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

      messagesRef.current = [...messagesRef.current, userMessage, assistantMessage];
      setMessages(messagesRef.current);
      setAwaitingConfirmation(false);
      setSending(true);
      setLivePhase(t("tool.thinking"));
      startedAtRef.current = Date.now();

      const controller = new AbortController();
      abortRef.current = controller;
      const steps: StepRecord[] = [];

      function updateAssistant(patch: Partial<ChatMessage>) {
        messagesRef.current = messagesRef.current.map((message) =>
          message.id === assistantId ? { ...message, ...patch } : message,
        );
        setMessages(messagesRef.current);
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
            const next = messagesRef.current.map((message) =>
              message.id === assistantId ? finalized : message,
            );
            const firstUser = next.find((message) => message.role === "user");
            // Persist to storage BEFORE announcing the conversation id: the
            // sidebar refreshes its list off the id-change callback below,
            // and it must find the entry already in storage when it reads
            // it, or a new chat only shows up in the list after a manual
            // page reload.
            saveConversation(finalId, firstUser ? firstUser.content.slice(0, 60) : t("sidebar.new_chat"), next);
            messagesRef.current = next;
            setMessages(next);
            setConversationId(finalId);
            onConversationId?.(finalId);
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

  const approve = useCallback(() => send(t("chat.approve_text")), [send, t]);
  const reject = useCallback(() => send(t("chat.reject_text")), [send, t]);

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
