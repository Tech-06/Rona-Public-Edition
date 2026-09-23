import { useCallback, useEffect, useRef, useState } from "react";
import { streamChat } from "../api/sse";
import { useT } from "../components/LanguageProvider";
import { fetchMessages, syncFromServer } from "../lib/storage";
import { agentPhaseLabel, confirmPhaseLabel, toolLabel } from "../lib/toolLabels";
import type { ChatMessage, ProgressEvent, StepRecord } from "../types";

function makeId(): string {
  return `${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
}

export function useChat(initialConversationId: string | null, onConversationId?: (id: string) => void) {
  const t = useT();
  const [conversationId, setConversationId] = useState<string | null>(initialConversationId);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  // Mirrors `messages` synchronously (unlike the state itself, which React
  // only applies once it gets around to processing the update). onDone
  // needs the up-to-date list *right now* -- see onDone below.
  const messagesRef = useRef<ChatMessage[]>([]);
  const [messagesLoading, setMessagesLoading] = useState(Boolean(initialConversationId));
  const [sending, setSending] = useState(false);
  const sendingRef = useRef(false);
  const [livePhase, setLivePhase] = useState<string | null>(null);
  const [awaitingConfirmation, setAwaitingConfirmation] = useState(false);
  const abortRef = useRef<AbortController | null>(null);
  const startedAtRef = useRef<number>(0);

  // The transcript now lives server-side (backend/graph/history.py), not
  // in localStorage -- opening a conversation means fetching it. A given
  // useChat instance is remounted (via App.tsx's `chatKey`) rather than
  // updated whenever the user picks a different conversation, so
  // initialConversationId is effectively fixed for this instance's
  // lifetime and this only ever needs to run once, on mount.
  useEffect(() => {
    if (!initialConversationId) return;
    let cancelled = false;
    setMessagesLoading(true);
    fetchMessages(initialConversationId)
      .then((loaded) => {
        if (cancelled) return;
        messagesRef.current = loaded;
        setMessages(loaded);
      })
      .catch(() => {
        if (cancelled) return;
        messagesRef.current = [];
        setMessages([]);
      })
      .finally(() => {
        if (!cancelled) setMessagesLoading(false);
      });
    return () => {
      cancelled = true;
    };
    // Mount-once, see comment above.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Catches up a conversation whose turn kept running (and got recorded,
  // see backend/app/main.py's _stream_worker) after this client stopped
  // watching it -- a phone app backgrounded mid-turn, put to sleep by the
  // OS, and reopened later. Only refetches when nothing is in flight
  // locally, so it can never clobber an optimistic in-progress bubble.
  useEffect(() => {
    function handleVisibility() {
      if (document.visibilityState !== "visible") return;
      if (sendingRef.current || !conversationId) return;
      fetchMessages(conversationId)
        .then((loaded) => {
          messagesRef.current = loaded;
          setMessages(loaded);
        })
        .catch(() => {
          // best effort -- try again next time the tab becomes visible
        });
    }
    document.addEventListener("visibilitychange", handleVisibility);
    return () => document.removeEventListener("visibilitychange", handleVisibility);
  }, [conversationId]);

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

      // Captured before this turn's pair is appended, so a later error can
      // tell "the server never got this turn" (still == baseline) apart
      // from "it got recorded despite the stream dying on us" (> baseline)
      // -- see onError below.
      const baseMessageCount = messagesRef.current.length;
      // Resolved as soon as the "conversation" SSE frame arrives, which is
      // sooner than React re-renders with the new conversationId state --
      // onError needs it immediately, not on the next render.
      let resolvedConversationId = conversationId;

      messagesRef.current = [...messagesRef.current, userMessage, assistantMessage];
      setMessages(messagesRef.current);
      setAwaitingConfirmation(false);
      setSending(true);
      sendingRef.current = true;
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
            resolvedConversationId = id;
            setConversationId((current) => current ?? id);
          },
          onProgress: handleProgress,
          onDone: async (result) => {
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
            messagesRef.current = next;
            setMessages(next);
            setConversationId(finalId);
            // The backend already persisted this turn before publishing
            // "done" (see _stream_worker), so the sidebar's list is
            // refreshed BEFORE announcing the conversation id: App.tsx
            // reloads its list off that callback, and it must already
            // find the entry there, or a new chat only shows up after a
            // manual page reload.
            try {
              await syncFromServer();
            } catch {
              // best effort -- the periodic sync in useConversationSync
              // will pick this up on its next tick either way
            }
            onConversationId?.(finalId);
            setAwaitingConfirmation(result.status === "confirmation_required");
            setSending(false);
            sendingRef.current = false;
            setLivePhase(null);
          },
          onError: (detail) => {
            updateAssistant({ pending: false, error: detail });
            setSending(false);
            sendingRef.current = false;
            setLivePhase(null);
            // The stream can die (network drop, backgrounded tab killed by
            // the OS, ...) after the backend already finished and recorded
            // the turn -- reconcile with the server rather than leaving a
            // real reply permanently hidden behind a local error bubble.
            if (resolvedConversationId) {
              const idToCheck = resolvedConversationId;
              fetchMessages(idToCheck)
                .then((loaded) => {
                  if (loaded.length <= baseMessageCount) return;
                  messagesRef.current = loaded;
                  setMessages(loaded);
                  void syncFromServer();
                })
                .catch(() => {
                  // genuinely unreachable -- the error bubble stands
                });
            }
          },
        },
        controller.signal,
      );
    },
    [conversationId, onConversationId, sending, t],
  );

  const approve = useCallback(() => send(t("chat.approve_text")), [send, t]);
  const reject = useCallback(() => send(t("chat.reject_text")), [send, t]);

  const stop = useCallback(() => {
    abortRef.current?.abort();
  }, []);

  return {
    conversationId,
    messages,
    messagesLoading,
    sending,
    livePhase,
    awaitingConfirmation,
    send,
    approve,
    reject,
    stop,
  };
}
