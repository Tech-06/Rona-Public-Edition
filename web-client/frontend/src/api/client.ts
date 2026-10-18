export class ApiError extends Error {
  status: number;
  /** Machine-readable error code from the BFF's `{detail, code}` body. */
  code?: string;
  /** Extra seconds hint on 429 `too_many_attempts` responses. */
  retryAfter?: number;

  constructor(status: number, message: string, code?: string, retryAfter?: number) {
    super(message);
    this.status = status;
    this.code = code;
    this.retryAfter = retryAfter;
  }
}

/** Fired when any API call is rejected with 401 `login_required` (cookie
 * missing or expired) so the AuthProvider can show the login form again
 * without a full page reload. */
export const AUTH_REQUIRED_EVENT = "rona:auth-required";

export function notifyAuthRequired(): void {
  window.dispatchEvent(new CustomEvent(AUTH_REQUIRED_EVENT));
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, {
    // Everything behind these endpoints is live server state (the shared
    // conversation list above all) -- a response reused from the HTTP
    // cache would show one device a stale copy of what another just wrote.
    cache: "no-store",
    credentials: "same-origin",
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...(init?.headers ?? {}),
    },
  });
  if (!response.ok) {
    let detail = response.statusText;
    let code: string | undefined;
    let retryAfter: number | undefined;
    try {
      const body = await response.json();
      detail = body.detail ?? detail;
      if (typeof body.code === "string") code = body.code;
      if (typeof body.retry_after === "number") retryAfter = body.retry_after;
    } catch {
      // response had no JSON body
    }
    if (response.status === 401 && code === "login_required") {
      notifyAuthRequired();
    }
    throw new ApiError(response.status, detail, code, retryAfter);
  }
  if (response.status === 204) {
    return undefined as T;
  }
  return (await response.json()) as T;
}

export const api = {
  get: <T>(path: string) => request<T>(path),
  post: <T>(path: string, body?: unknown) =>
    request<T>(path, { method: "POST", body: JSON.stringify(body ?? {}) }),
  put: <T>(path: string, body?: unknown) =>
    request<T>(path, { method: "PUT", body: JSON.stringify(body ?? {}) }),
  patch: <T>(path: string, body?: unknown) =>
    request<T>(path, { method: "PATCH", body: JSON.stringify(body ?? {}) }),
  del: <T>(path: string) =>
    request<T>(path, { method: "DELETE", body: JSON.stringify({}) }),
};
