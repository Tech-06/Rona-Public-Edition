import { afterEach, describe, expect, it, vi } from "vitest";
import { jsonResponse, mockFetch } from "../test/mockFetch";
import { ApiError, AUTH_REQUIRED_EVENT, api } from "./client";

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("api client", () => {
  it("parses code and retry_after into ApiError", async () => {
    mockFetch(() =>
      jsonResponse(429, { detail: "slow down", code: "too_many_attempts", retry_after: 12 }),
    );
    const error = (await api.post("/auth/login", { password: "x" }).catch((e) => e)) as ApiError;
    expect(error).toBeInstanceOf(ApiError);
    expect(error.status).toBe(429);
    expect(error.code).toBe("too_many_attempts");
    expect(error.retryAfter).toBe(12);
    expect(error.message).toBe("slow down");
  });

  it("dispatches rona:auth-required on 401 login_required", async () => {
    mockFetch(() => jsonResponse(401, { detail: "login", code: "login_required" }));
    const listener = vi.fn();
    window.addEventListener(AUTH_REQUIRED_EVENT, listener);
    await expect(api.get("/api/status")).rejects.toBeInstanceOf(ApiError);
    window.removeEventListener(AUTH_REQUIRED_EVENT, listener);
    expect(listener).toHaveBeenCalledTimes(1);
  });

  it("does not dispatch for 401 invalid_password", async () => {
    mockFetch(() => jsonResponse(401, { detail: "no", code: "invalid_password" }));
    const listener = vi.fn();
    window.addEventListener(AUTH_REQUIRED_EVENT, listener);
    await expect(api.post("/auth/login", {})).rejects.toBeInstanceOf(ApiError);
    window.removeEventListener(AUTH_REQUIRED_EVENT, listener);
    expect(listener).not.toHaveBeenCalled();
  });

  it("sends same-origin credentials and JSON content type", async () => {
    const fetchMock = mockFetch(() => jsonResponse(200, {}));
    await api.post("/x", { a: 1 });
    const init = fetchMock.mock.calls[0][1] as RequestInit;
    expect(init.credentials).toBe("same-origin");
    expect((init.headers as Record<string, string>)["Content-Type"]).toBe("application/json");
  });
});
