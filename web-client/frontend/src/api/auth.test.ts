import { afterEach, describe, expect, it, vi } from "vitest";
import { jsonResponse, mockFetch } from "../test/mockFetch";
import { authApi } from "./auth";

afterEach(() => {
  vi.unstubAllGlobals();
});

function lastCall(fetchMock: ReturnType<typeof mockFetch>) {
  const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
  return { url, init, headers: init.headers as Record<string, string> };
}

describe("authApi", () => {
  it("status is a GET", async () => {
    const f = mockFetch(() => jsonResponse(200, { authenticated: false, password_set: true }));
    expect(await authApi.status()).toEqual({ authenticated: false, password_set: true });
    expect(lastCall(f).url).toBe("/auth/status");
    expect(lastCall(f).init.method).toBeUndefined();
  });

  it("login posts the password as JSON", async () => {
    const f = mockFetch(() => jsonResponse(200, { authenticated: true }));
    await authApi.login("secret");
    const c = lastCall(f);
    expect(c.url).toBe("/auth/login");
    expect(c.init.method).toBe("POST");
    expect(c.headers["Content-Type"]).toBe("application/json");
    expect(JSON.parse(c.init.body as string)).toEqual({ password: "secret" });
  });

  it("logout posts an empty JSON object", async () => {
    const f = mockFetch(() => jsonResponse(200, { authenticated: false }));
    await authApi.logout();
    const c = lastCall(f);
    expect(c.url).toBe("/auth/logout");
    expect(c.headers["Content-Type"]).toBe("application/json");
    expect(JSON.parse(c.init.body as string)).toEqual({});
  });

  it("changePassword sends current and new", async () => {
    const f = mockFetch(() => jsonResponse(200, { ok: true }));
    await authApi.changePassword("old-pass", "new-password-1");
    const c = lastCall(f);
    expect(c.url).toBe("/auth/password");
    expect(JSON.parse(c.init.body as string)).toEqual({
      current: "old-pass",
      new: "new-password-1",
    });
  });
});
