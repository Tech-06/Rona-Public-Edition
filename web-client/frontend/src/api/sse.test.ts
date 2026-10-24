import { afterEach, describe, expect, it, vi } from "vitest";
import { streamChat, type StreamHandlers } from "./sse";
import { jsonResponse } from "../test/mockFetch";

afterEach(() => {
  vi.unstubAllGlobals();
});

const enc = new TextEncoder();
const frame = (id: number, event: string, data: unknown) =>
  `id: ${id}\nevent: ${event}\ndata: ${JSON.stringify(data)}\n\n`;
const DONE = {
  conversation_id: "c1",
  reply: "hi",
  status: "ok",
  tool_calls: [],
};

/** Stream that emits chunks, then either ends cleanly or errors. */
function sseResponse(
  chunks: string[],
  end: "close" | "error" = "close",
): Response {
  let i = 0;
  const body = new ReadableStream<Uint8Array>({
    pull(controller) {
      if (i < chunks.length) {
        controller.enqueue(enc.encode(chunks[i++]));
      } else if (end === "close") {
        controller.close();
      } else {
        controller.error(new TypeError("network error"));
      }
    },
  });
  return new Response(body, {
    status: 200,
    headers: { "Content-Type": "text/event-stream" },
  });
}

function handlers() {
  const h = {
    onConversationId: vi.fn(),
    onProgress: vi.fn(),
    onDone: vi.fn(),
    onError: vi.fn(),
    onAbort: vi.fn(),
  };
  return h satisfies StreamHandlers;
}

const fast = { reconnectDelaysMs: [0, 0, 0] };

function stubFetch(
  ...impls: Array<(init?: RequestInit) => Response | Promise<Response>>
) {
  const fn = vi.fn((_url: unknown, init?: RequestInit) => {
    const impl = impls[Math.min(fn.mock.calls.length - 1, impls.length - 1)];
    try {
      return Promise.resolve(impl(init));
    } catch (e) {
      return Promise.reject(e);
    }
  });
  vi.stubGlobal("fetch", fn);
  return fn;
}

describe("streamChat", () => {
  it("resumes with Last-Event-ID after a drop and finishes once", async () => {
    const fetchFn = stubFetch(
      () =>
        sseResponse(
          [
            frame(0, "conversation", { conversation_id: "c1" }),
            ": ping\n\n",
            frame(3, "progress", { type: "agent_start" }),
          ],
          "error",
        ),
      () =>
        sseResponse([
          frame(4, "progress", { type: "agent_start" }),
          frame(5, "done", DONE),
        ]),
    );
    const h = handlers();
    await streamChat("hello", null, h, undefined, fast);
    expect(fetchFn).toHaveBeenCalledTimes(2);
    const first = fetchFn.mock.calls[0][1] as RequestInit;
    const second = fetchFn.mock.calls[1][1] as RequestInit;
    expect(
      (first.headers as Record<string, string>)["Last-Event-ID"],
    ).toBeUndefined();
    expect((second.headers as Record<string, string>)["Last-Event-ID"]).toBe(
      "3",
    );
    expect(JSON.parse(second.body as string)).toEqual({
      message: "hello",
      conversation_id: "c1",
    });
    expect(h.onProgress).toHaveBeenCalledTimes(2);
    expect(h.onDone).toHaveBeenCalledTimes(1);
    expect(h.onError).not.toHaveBeenCalled();
    expect(h.onAbort).not.toHaveBeenCalled();
  });

  it("resumes when the stream ends cleanly without a done frame", async () => {
    const fetchFn = stubFetch(
      () => sseResponse([frame(0, "conversation", { conversation_id: "c1" })]),
      () => sseResponse([frame(1, "done", DONE)]),
    );
    const h = handlers();
    await streamChat("x", null, h, undefined, fast);
    expect(fetchFn).toHaveBeenCalledTimes(2);
    expect(h.onDone).toHaveBeenCalledTimes(1);
  });

  it("does not reconnect when no event id was received", async () => {
    const fetchFn = stubFetch(() => sseResponse([": ping\n\n"], "error"));
    const h = handlers();
    await streamChat("x", "c1", h, undefined, fast);
    expect(fetchFn).toHaveBeenCalledTimes(1);
    expect(h.onError).toHaveBeenCalledTimes(1);
    expect(h.onDone).not.toHaveBeenCalled();
  });

  it("reports a network error before headers via onError", async () => {
    stubFetch(() => {
      throw new TypeError("Failed to fetch");
    });
    const h = handlers();
    await streamChat("x", null, h, undefined, fast);
    expect(h.onError).toHaveBeenCalledTimes(1);
    expect(h.onError.mock.calls[0][0]).toBe("Failed to fetch");
  });

  it("gives up after 3 failed reconnects with a single onError", async () => {
    const fetchFn = stubFetch(
      () =>
        sseResponse([frame(2, "progress", { type: "agent_start" })], "error"),
      () => {
        throw new TypeError("down");
      },
    );
    const h = handlers();
    await streamChat("x", "c1", h, undefined, fast);
    expect(fetchFn).toHaveBeenCalledTimes(4);
    expect(h.onError).toHaveBeenCalledTimes(1);
    expect(h.onDone).not.toHaveBeenCalled();
  });

  it("409 conversation_busy: onError with detail and code, no reconnect", async () => {
    const fetchFn = stubFetch(() =>
      jsonResponse(409, { detail: "Mesgul", code: "conversation_busy" }),
    );
    const h = handlers();
    await streamChat("x", "c1", h, undefined, fast);
    expect(fetchFn).toHaveBeenCalledTimes(1);
    expect(h.onError).toHaveBeenCalledTimes(1);
    expect(h.onError).toHaveBeenCalledWith("Mesgul", {
      status: 409,
      code: "conversation_busy",
    });
  });

  it("410 on resume: onError with run_not_found", async () => {
    const fetchFn = stubFetch(
      () =>
        sseResponse([frame(1, "progress", { type: "agent_start" })], "error"),
      () => jsonResponse(410, { detail: "gone", code: "run_not_found" }),
    );
    const h = handlers();
    await streamChat("x", "c1", h, undefined, fast);
    expect(fetchFn).toHaveBeenCalledTimes(2);
    expect(h.onError).toHaveBeenCalledTimes(1);
    expect(h.onError).toHaveBeenCalledWith("gone", {
      status: 410,
      code: "run_not_found",
    });
  });

  it("abort during fetch calls onAbort only", async () => {
    const controller = new AbortController();
    stubFetch(
      (init) =>
        new Promise<Response>((_resolve, reject) => {
          init?.signal?.addEventListener("abort", () =>
            reject(new DOMException("aborted", "AbortError")),
          );
        }),
    );
    const h = handlers();
    const p = streamChat("x", null, h, controller.signal, fast);
    controller.abort();
    await p;
    expect(h.onAbort).toHaveBeenCalledTimes(1);
    expect(h.onError).not.toHaveBeenCalled();
  });

  it("abort while reading calls onAbort only", async () => {
    const controller = new AbortController();
    stubFetch((init) => {
      const body = new ReadableStream<Uint8Array>({
        start(c) {
          c.enqueue(
            enc.encode(frame(0, "conversation", { conversation_id: "c1" })),
          );
          init?.signal?.addEventListener("abort", () =>
            c.error(new DOMException("aborted", "AbortError")),
          );
        },
      });
      return new Response(body, { status: 200 });
    });
    const h = handlers();
    h.onConversationId.mockImplementation(() => controller.abort());
    await streamChat("x", null, h, controller.signal, fast);
    expect(h.onAbort).toHaveBeenCalledTimes(1);
    expect(h.onError).not.toHaveBeenCalled();
    expect(h.onDone).not.toHaveBeenCalled();
  });

  it("abort during reconnect backoff calls onAbort and stops", async () => {
    const controller = new AbortController();
    const fetchFn = stubFetch(() =>
      sseResponse([frame(1, "progress", { type: "agent_start" })], "error"),
    );
    const h = handlers();
    h.onProgress.mockImplementation(() => {
      setTimeout(() => controller.abort(), 5);
    });
    await streamChat("x", "c1", h, controller.signal, {
      reconnectDelaysMs: [10_000],
    });
    expect(fetchFn).toHaveBeenCalledTimes(1);
    expect(h.onAbort).toHaveBeenCalledTimes(1);
    expect(h.onError).not.toHaveBeenCalled();
  });

  it("keeps the last real id when a resume stream starts with frame 0 and drops again", async () => {
    const fetchFn = stubFetch(
      () =>
        sseResponse(
          [
            frame(0, "conversation", { conversation_id: "c1" }),
            frame(7, "progress", { type: "agent_start" }),
          ],
          "error",
        ),
      () =>
        sseResponse(
          [frame(0, "conversation", { conversation_id: "c1" })],
          "error",
        ),
      () => sseResponse([frame(8, "done", DONE)]),
    );
    const h = handlers();
    await streamChat("x", null, h, undefined, fast);
    const ids = fetchFn.mock.calls.map(
      (call) =>
        ((call[1] as RequestInit).headers as Record<string, string>)[
          "Last-Event-ID"
        ],
    );
    expect(ids).toEqual([undefined, "7", "7"]);
    expect(h.onDone).toHaveBeenCalledTimes(1);
  });

  it("terminates when every connection sends only frame 0 and drops", async () => {
    const fetchFn = stubFetch(() =>
      sseResponse(
        [frame(0, "conversation", { conversation_id: "c1" })],
        "error",
      ),
    );
    const h = handlers();
    await streamChat("x", null, h, undefined, fast);
    expect(fetchFn).toHaveBeenCalledTimes(4);
    expect(h.onError).toHaveBeenCalledTimes(1);
  });

  it("retries a 503 on resume and then completes", async () => {
    const fetchFn = stubFetch(
      () =>
        sseResponse([frame(2, "progress", { type: "agent_start" })], "error"),
      () => jsonResponse(503, { detail: "restarting" }),
      () => sseResponse([frame(3, "done", DONE)]),
    );
    const h = handlers();
    await streamChat("x", "c1", h, undefined, fast);
    expect(fetchFn).toHaveBeenCalledTimes(3);
    expect(h.onDone).toHaveBeenCalledTimes(1);
    expect(h.onError).not.toHaveBeenCalled();
  });

  it("gives up on a persistent 502 on resume after the retry budget", async () => {
    const fetchFn = stubFetch(
      () =>
        sseResponse([frame(2, "progress", { type: "agent_start" })], "error"),
      () => jsonResponse(502, { detail: "bad gateway" }),
    );
    const h = handlers();
    await streamChat("x", "c1", h, undefined, fast);
    expect(fetchFn).toHaveBeenCalledTimes(4);
    expect(h.onError).toHaveBeenCalledTimes(1);
  });

  it("does not retry a 503 on the initial request", async () => {
    const fetchFn = stubFetch(() => jsonResponse(503, { detail: "down" }));
    const h = handlers();
    await streamChat("x", "c1", h, undefined, fast);
    expect(fetchFn).toHaveBeenCalledTimes(1);
    expect(h.onError).toHaveBeenCalledWith("down", {
      status: 503,
      code: undefined,
    });
  });
});
