import { useCallback, useEffect, useRef, useState } from "react";
import { streamChat } from "../api/sse";
import { useT } from "../components/LanguageProvider";
import {
  fetchConversation,
  loadIndex,
  onConversationsChanged,
  syncFromServer,
  type ServerConversation,
} from "../lib/storage";
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
  // The server's updatedAt for the transcript currently on screen. Compared
  // against the synced conversation list to notice that another device (or
  // a turn that kept running after this one stopped listening) has added to
  // it since -- see the live-refresh effect below.
  const loadedUpdatedAtRef = useRef<number>(0);
  // True until the initial fetch of an opened conversation settles -- the
  // live-refresh effect would otherwise fire a second, identical fetch for
  // the very sync that lands while the first one is still in flight.
  const initialLoadPendingRef = useRef(Boolean(initialConversationId));

  function showServerConversation(conversation: ServerConversation) {
    messagesRef.current = conversation.messages;
    setMessages(conversation.messages);
    loadedUpdatedAtRef.current = conversation.updatedAt;
  }

  // The transcript lives server-side (backend/graph/history.py) --
  // opening a conversation means fetching it. A given useChat instance is
  // remounted (via App.tsx's `chatKey`) rather than updated whenever the
  // user picks a different conversation, so initialConversationId is
  // effectively fixed for this instance's lifetime and this only ever
  // needs to run once, on mount.
  useEffect(() => {
    if (!initialConversationId) return;
    let cancelled = false;
    setMessagesLoading(true);
    fetchConversation(initialConversationId)
      .then((loaded) => {
        if (cancelled) return;
        showServerConversation(loaded ?? { messages: [], updatedAt: 0 });
      })
      .catch(() => {
        if (cancelled) return;
        showServerConversation({ messages: [], updatedAt: 0 });
      })
      .finally(() => {
        initialLoadPendingRef.current = false;
        if (!cancelled) setMessagesLoading(false);
      });
    return () => {
      cancelled = true;
    };
    // Mount-once, see comment above.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Live refresh: every sync (periodic, on returning to the app, after a
  // turn) re-reads the shared conversation list. When this conversation's
  // entry there is newer than the transcript on screen, someone else wrote
  // to it -- a message sent from another device, or a turn this client
  // started but stopped watching (a phone app backgrounded mid-turn; the
  // backend finishes and records it regardless) -- so fetch it again.
  // Never while a send of our own is in flight, so an optimistic
  // in-progress bubble can't be clobbered.
  useEffect(() => {
    if (!conversationId) return;
    return onConversationsChanged(() => {
      if (sendingRef.current || initialLoadPendingRef.current) return;
      const summary = loadIndex().find((entry) => entry.conversationId === conversationId);
      if (!summary || summary.updatedAt <= loadedUpdatedAtRef.current) return;
      fetchConversation(conversationId)
        .then((loaded) => {
          if (loaded && !sendingRef.current) showServerConversation(loaded);
        })
        .catch(() => {
          // best effort -- the next sync tries again
        });
    });
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
            // What's on screen now matches what the server just recorded,
            // so the live-refresh effect mustn't mistake our own turn for
            // someone else's and refetch it.
            const recorded = loadIndex().find((entry) => entry.conversationId === finalId);
            if (recorded) {
              loadedUpdatedAtRef.current = Math.max(loadedUpdatedAtRef.current, recorded.updatedAt);
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
            // real reply hidden behind a local error bubble. If the turn is
            // still running there, the live-refresh effect catches it once
            // it's recorded; if it genuinely failed, the server never got
            // it and the error bubble stands.
            if (resolvedConversationId) {
              fetchConversation(resolvedConversationId)
                .then((loaded) => {
                  if (!loaded || loaded.messages.length <= baseMessageCount) return;
                  showServerConversation(loaded);
                  void syncFromServer().catch(() => {});
                })
                .catch(() => {
                  // unreachable right now -- the next sync retries
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
