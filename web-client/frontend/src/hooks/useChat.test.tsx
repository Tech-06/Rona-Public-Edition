import { afterEach, describe, expect, it, vi } from "vitest";
import { act, renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { LanguageProvider } from "../components/LanguageProvider";
import { jsonResponse } from "../test/mockFetch";
import { useChat } from "./useChat";

afterEach(() => {
  vi.unstubAllGlobals();
});

const enc = new TextEncoder();
const wrapper = ({ children }: { children: ReactNode }) => (
  <LanguageProvider>{children}</LanguageProvider>
);

function stub(handler: (url: string, init?: RequestInit) => Response | Promise<Response>) {
  vi.stubGlobal(
    "fetch",
    vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      try {
        return Promise.resolve(handler(String(input), init));
      } catch (e) {
        return Promise.reject(e);
      }
    }),
  );
}

describe("useChat sending state", () => {
  it("resets after a network error before headers", async () => {
    stub(() => {
      throw new TypeError("Failed to fetch");
    });
    const { result } = renderHook(() => useChat(null), { wrapper });
    act(() => result.current.send("hi"));
    await waitFor(() => expect(result.current.sending).toBe(false));
    expect(result.current.livePhase).toBeNull();
    expect(result.current.messages[1].pending).toBe(false);
    expect(result.current.messages[1].error).toBeTruthy();
  });

  it("resets after a 409 and shows the server detail", async () => {
    stub(() => jsonResponse(409, { detail: "busy elsewhere", code: "conversation_busy" }));
    const { result } = renderHook(() => useChat(null), { wrapper });
    act(() => result.current.send("hi"));
    await waitFor(() => expect(result.current.sending).toBe(false));
    expect(result.current.messages[1].error).toBe("busy elsewhere");
  });

  it("resets after a user stop", async () => {
    stub(
      (_url, init) =>
        new Promise<Response>((_resolve, reject) => {
          init?.signal?.addEventListener("abort", () =>
            reject(new DOMException("aborted", "AbortError")),
          );
        }),
    );
    const { result } = renderHook(() => useChat(null), { wrapper });
    act(() => result.current.send("hi"));
    expect(result.current.sending).toBe(true);
    act(() => result.current.stop());
    await waitFor(() => expect(result.current.sending).toBe(false));
    expect(result.current.livePhase).toBeNull();
    expect(result.current.messages[1].pending).toBe(false);
  });

  it("resets after done", async () => {
    const done = { conversation_id: "c1", reply: "yo", status: "ok", tool_calls: [] };
    stub((url) => {
      if (url === "/chat/stream") {
        const text = `id: 1\nevent: done\ndata: ${JSON.stringify(done)}\n\n`;
        return new Response(
          new ReadableStream({
            start(c) {
              c.enqueue(enc.encode(text));
              c.close();
            },
          }),
          { status: 200 },
        );
      }
      return jsonResponse(200, []);
    });
    const { result } = renderHook(() => useChat(null), { wrapper });
    act(() => result.current.send("hi"));
    await waitFor(() => expect(result.current.sending).toBe(false));
    expect(result.current.messages[1].content).toBe("yo");
  });
});

describe("useChat structured confirmation", () => {
  function sse(done: object): Response {
    const text = `id: 1\nevent: done\ndata: ${JSON.stringify(done)}\n\n`;
    return new Response(
      new ReadableStream({
        start(c) {
          c.enqueue(enc.encode(text));
          c.close();
        },
      }),
      { status: 200 },
    );
  }

  async function setup() {
    const bodies: Record<string, unknown>[] = [];
    let turn = 0;
    stub((url, init) => {
      if (url === "/chat/stream") {
        bodies.push(JSON.parse(String(init?.body)));
        turn += 1;
        return turn === 1
          ? sse({
              conversation_id: "c1",
              reply: "sure?",
              status: "confirmation_required",
              tool_calls: [{ name: "delete_person", args: { person_id: 1 } }],
              pending_hash: "h-123",
            })
          : sse({ conversation_id: "c1", reply: "done", status: "ok", tool_calls: null });
      }
      return jsonResponse(200, []);
    });
    const hook = renderHook(() => useChat(null), { wrapper });
    act(() => hook.result.current.send("delete him"));
    await waitFor(() => expect(hook.result.current.awaitingConfirmation).toBe(true));
    return { hook, bodies };
  }

  it("approve and reject send the structured decision with the pending hash", async () => {
    const { hook, bodies } = await setup();
    act(() => hook.result.current.approve());
    await waitFor(() => expect(hook.result.current.sending).toBe(false));
    expect(bodies[1].confirmation).toEqual({ approved: true, pending_hash: "h-123" });
    expect(typeof bodies[1].message).toBe("string");

    const second = await setup();
    act(() => second.hook.result.current.reject());
    await waitFor(() => expect(second.hook.result.current.sending).toBe(false));
    expect(second.bodies[1].confirmation).toEqual({ approved: false, pending_hash: "h-123" });
  });

  it("typed text carries no confirmation field", async () => {
    const { hook, bodies } = await setup();
    act(() => hook.result.current.send("yes go ahead"));
    await waitFor(() => expect(hook.result.current.sending).toBe(false));
    expect(bodies[1]).not.toHaveProperty("confirmation");
    expect(bodies[1].message).toBe("yes go ahead");
  });
});
