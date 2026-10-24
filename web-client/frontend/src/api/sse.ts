import { t } from "../lib/i18n";
import { notifyAuthRequired } from "./client";
import type { ChatResult, ConfirmationDecision, ProgressEvent } from "../types";

interface SseFrame {
  id: string | null;
  event: string | null;
  data: string;
}

function parseFrame(block: string): SseFrame {
  let id: string | null = null;
  let event: string | null = null;
  const dataLines: string[] = [];
  for (const line of block.split("\n")) {
    if (line.startsWith("id:")) {
      id = line.slice(3).trim();
    } else if (line.startsWith("event:")) {
      event = line.slice(6).trim();
    } else if (line.startsWith("data:")) {
      dataLines.push(line.slice(5).trim());
    }
  }
  return { id, event, data: dataLines.join("\n") };
}

export interface StreamErrorInfo {
  status?: number;
  code?: string;
}

export interface StreamHandlers {
  onConversationId?: (conversationId: string) => void;
  onProgress?: (event: ProgressEvent) => void;
  onDone?: (result: ChatResult) => void;
  /** Terminal: the turn failed (after any reconnect attempts). */
  onError?: (detail: string, info?: StreamErrorInfo) => void;
  /** Terminal: the caller aborted via its AbortSignal. */
  onAbort?: () => void;
}

export interface StreamOptions {
  /** Delays (ms) before each reconnect attempt; its length is the attempt cap. */
  reconnectDelaysMs?: number[];
}

const DEFAULT_RECONNECT_DELAYS_MS = [1000, 2000, 4000];

// A proxy in front of a restarting backend answers these; a resume may retry.
// 401/409/410 and the like mean the turn is gone or unauthorised: never retry.
const RETRYABLE_RESUME_STATUSES = new Set([502, 503, 504]);

function isAbort(error: unknown, signal?: AbortSignal): boolean {
  return (
    Boolean(signal?.aborted) ||
    (error as { name?: string } | null)?.name === "AbortError"
  );
}

function sleep(ms: number, signal?: AbortSignal): Promise<void> {
  return new Promise((resolve) => {
    if (signal?.aborted) return resolve();
    const timer = setTimeout(done, ms);
    function done() {
      clearTimeout(timer);
      signal?.removeEventListener("abort", done);
      resolve();
    }
    signal?.addEventListener("abort", done);
  });
}

/**
 * Streams one chat turn. Never rejects; exactly one of onDone / onError /
 * onAbort is invoked. A dropped connection (or a stream that ends without a
 * `done` frame) is resumed with `Last-Event-ID` when at least one event id
 * was received and the conversation id is known.
 */
export async function streamChat(
  message: string,
  conversationId: string | null,
  handlers: StreamHandlers,
  signal?: AbortSignal,
  options: StreamOptions = {},
  confirmation?: ConfirmationDecision,
): Promise<void> {
  const delays = options.reconnectDelaysMs ?? DEFAULT_RECONNECT_DELAYS_MS;
  let lastEventId: string | null = null;
  let lastNumericId = -1;
  let knownConversationId = conversationId;
  let finished = false;
  let attempt = 0;

  const finish = (fn: () => void) => {
    if (finished) return;
    finished = true;
    fn();
  };
  const fail = (detail: string, info?: StreamErrorInfo) =>
    finish(() => handlers.onError?.(detail, info));

  const wrapped: StreamHandlers = {
    ...handlers,
    onConversationId: (id) => {
      knownConversationId = id;
      handlers.onConversationId?.(id);
    },
    onDone: (result) => finish(() => handlers.onDone?.(result)),
    onError: (detail) => fail(detail),
  };

  while (!finished) {
    const resuming = lastEventId !== null;
    let failure: string | null = null;
    try {
      const headers: Record<string, string> = {
        "Content-Type": "application/json",
      };
      if (resuming) headers["Last-Event-ID"] = lastEventId as string;
      const response = await fetch("/chat/stream", {
        method: "POST",
        headers,
        credentials: "same-origin",
        body: JSON.stringify(
          confirmation
            ? { message, conversation_id: knownConversationId, confirmation }
            : { message, conversation_id: knownConversationId },
        ),
        signal,
      });
      if (resuming && RETRYABLE_RESUME_STATUSES.has(response.status)) {
        failure = response.statusText || t("sse.request_failed");
      } else if (!response.ok || !response.body) {
        let detail = response.statusText || t("sse.request_failed");
        let code: string | undefined;
        try {
          const body = await response.json();
          detail = body.detail ?? detail;
          code = body.code;
          if (response.status === 401 && body.code === "login_required") {
            notifyAuthRequired();
          }
        } catch {
          // no JSON body available
        }
        fail(detail, { status: response.status, code });
        break;
      }

      if (failure === null) {
        const reader = response.body!.getReader();
        const decoder = new TextDecoder("utf-8");
        let buffer = "";
        while (!finished) {
          const { value, done } = await reader.read();
          if (done) break;
          buffer += decoder.decode(value, { stream: true });
          buffer = buffer.replace(/\r\n/g, "\n");
          let separatorIndex = buffer.indexOf("\n\n");
          while (separatorIndex !== -1) {
            const rawBlock = buffer.slice(0, separatorIndex);
            buffer = buffer.slice(separatorIndex + 2);
            if (rawBlock.trim() && !rawBlock.startsWith(":")) {
              const frame = parseFrame(rawBlock);
              // The backend opens EVERY connection (resumes too) with `id: 0`
              // plus the "conversation" event. Treating that as progress would
              // rewind a resume to 0 (replaying the whole ring) and, for a
              // server that sends only frame 0 before dropping, reset the retry
              // budget forever. So the cursor only ever moves forward, and
              // only an id above 0 counts as progress for the retry budget.
              const numericId = frame.id === null ? NaN : Number(frame.id);
              if (Number.isInteger(numericId) && numericId > lastNumericId) {
                lastNumericId = numericId;
                lastEventId = String(numericId);
                if (numericId > 0) attempt = 0;
              }
              dispatchFrame(frame, wrapped);
            }
            separatorIndex = buffer.indexOf("\n\n");
          }
        }
        if (finished) break;
        failure = t("sse.stream_ended");
      }
    } catch (error) {
      if (isAbort(error, signal)) {
        finish(() => handlers.onAbort?.());
        break;
      }
      failure = (error as Error)?.message || t("sse.request_failed");
    }

    // Connection lost without a terminal frame: try to resume.
    if (
      lastEventId === null ||
      !knownConversationId ||
      attempt >= delays.length
    ) {
      fail(failure ?? t("sse.request_failed"), { code: "stream_lost" });
      break;
    }
    await sleep(delays[attempt], signal);
    attempt += 1;
    if (signal?.aborted) {
      finish(() => handlers.onAbort?.());
      break;
    }
  }
}

function dispatchFrame(frame: SseFrame, handlers: StreamHandlers): void {
  if (!frame.event || !frame.data) return;
  try {
    const payload = JSON.parse(frame.data);
    if (frame.event === "conversation") {
      handlers.onConversationId?.(payload.conversation_id);
    } else if (frame.event === "progress") {
      handlers.onProgress?.(payload as ProgressEvent);
    } else if (frame.event === "done") {
      handlers.onDone?.(payload as ChatResult);
    } else if (frame.event === "error") {
      handlers.onError?.(payload.detail ?? t("sse.unknown_error"));
    }
  } catch {
    // malformed frame, ignore
  }
}
