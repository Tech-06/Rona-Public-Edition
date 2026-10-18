import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { AUTH_REQUIRED_EVENT } from "../../api/client";
import { jsonResponse, mockFetch } from "../../test/mockFetch";
import { LanguageProvider } from "../LanguageProvider";
import { AuthProvider } from "./AuthProvider";

afterEach(() => {
  vi.unstubAllGlobals();
});

const PASSWORD_LABEL = /Parola|Password/;
const LOGIN_BUTTON = /Giriş yap|Sign in/;

function renderGate() {
  return render(
    <LanguageProvider>
      <AuthProvider>
        <div>secret-app</div>
      </AuthProvider>
    </LanguageProvider>,
  );
}

function typePassword(value: string) {
  fireEvent.change(screen.getByLabelText(PASSWORD_LABEL), { target: { value } });
}

function submit() {
  fireEvent.click(screen.getByRole("button", { name: LOGIN_BUTTON }));
}

const loggedOut = () => jsonResponse(200, { authenticated: false, password_set: true });

describe("AuthProvider", () => {
  it("shows the locked screen when no password is set", async () => {
    mockFetch(() => jsonResponse(200, { authenticated: false, password_set: false }));
    renderGate();
    expect(await screen.findByText("rona web password")).toBeTruthy();
    expect(screen.queryByText("secret-app")).toBeNull();
  });

  it("renders children when already authenticated", async () => {
    mockFetch(() => jsonResponse(200, { authenticated: true, password_set: true }));
    renderGate();
    expect(await screen.findByText("secret-app")).toBeTruthy();
  });

  it("shows an error message on invalid_password", async () => {
    mockFetch((url) =>
      url === "/auth/status" ? loggedOut() : jsonResponse(401, { detail: "x", code: "invalid_password" }),
    );
    renderGate();
    await screen.findByLabelText(PASSWORD_LABEL);
    typePassword("wrong");
    submit();
    expect(await screen.findByText(/Parola yanlış|Wrong password/)).toBeTruthy();
    expect(screen.queryByText("secret-app")).toBeNull();
  });

  it("counts down and disables submit on too_many_attempts", async () => {
    mockFetch((url) =>
      url === "/auth/status"
        ? loggedOut()
        : jsonResponse(429, { detail: "x", code: "too_many_attempts", retry_after: 2 }),
    );
    renderGate();
    await screen.findByLabelText(PASSWORD_LABEL);
    typePassword("pw");
    submit();
    expect(await screen.findByText(/2 sn|2 s\./)).toBeTruthy();
    typePassword("pw");
    const button = screen.getByRole("button", { name: LOGIN_BUTTON }) as HTMLButtonElement;
    expect(button.disabled).toBe(true);
    await waitFor(() => expect(button.disabled).toBe(false), { timeout: 4000 });
  });

  it("renders children after a successful login", async () => {
    mockFetch((url) =>
      url === "/auth/status" ? loggedOut() : jsonResponse(200, { authenticated: true }),
    );
    renderGate();
    await screen.findByLabelText(PASSWORD_LABEL);
    typePassword("right");
    submit();
    expect(await screen.findByText("secret-app")).toBeTruthy();
  });

  it("returns to the login form on rona:auth-required", async () => {
    mockFetch(() => jsonResponse(200, { authenticated: true, password_set: true }));
    renderGate();
    await screen.findByText("secret-app");
    act(() => {
      window.dispatchEvent(new CustomEvent(AUTH_REQUIRED_EVENT));
    });
    expect(await screen.findByLabelText(PASSWORD_LABEL)).toBeTruthy();
    expect(screen.queryByText("secret-app")).toBeNull();
  });
});
