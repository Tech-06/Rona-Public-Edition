import { t } from "../lib/i18n";
import type { ChatResult, ProgressEvent } from "../types";

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

export interface StreamHandlers {
  onConversationId?: (conversationId: string) => void;
  onProgress?: (event: ProgressEvent) => void;
  onDone?: (result: ChatResult) => void;
  onError?: (detail: string) => void;
}

export async function streamChat(
  message: string,
  conversationId: string | null,
  handlers: StreamHandlers,
  signal?: AbortSignal,
): Promise<void> {
  const response = await fetch("/chat/stream", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ message, conversation_id: conversationId }),
    signal,
  });
  if (!response.ok || !response.body) {
    let detail = response.statusText || t("sse.request_failed");
    try {
      const body = await response.json();
      detail = body.detail ?? detail;
    } catch {
      // no JSON body available
    }
    handlers.onError?.(detail);
    return;
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder("utf-8");
  let buffer = "";

  try {
    while (true) {
      const { value, done } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      let separatorIndex = buffer.indexOf("\n\n");
      while (separatorIndex !== -1) {
        const rawBlock = buffer.slice(0, separatorIndex);
        buffer = buffer.slice(separatorIndex + 2);
        if (rawBlock.trim() && !rawBlock.startsWith(":")) {
          const frame = parseFrame(rawBlock);
          dispatchFrame(frame, handlers);
        }
        separatorIndex = buffer.indexOf("\n\n");
      }
    }
  } catch (error) {
    if ((error as DOMException).name !== "AbortError") {
      handlers.onError?.((error as Error).message);
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
