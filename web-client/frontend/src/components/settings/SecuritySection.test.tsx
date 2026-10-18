import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { jsonResponse, mockFetch } from "../../test/mockFetch";
import { AuthProvider } from "../auth/AuthProvider";
import { LanguageProvider } from "../LanguageProvider";
import { SecuritySection } from "./SecuritySection";

afterEach(() => {
  vi.unstubAllGlobals();
});

async function renderSection(override?: (url: string) => Response | undefined) {
  const fetchMock = mockFetch(
    (url) =>
      override?.(url) ?? jsonResponse(200, { authenticated: true, password_set: true, ok: true }),
  );
  render(
    <LanguageProvider>
      <AuthProvider>
        <SecuritySection />
      </AuthProvider>
    </LanguageProvider>,
  );
  await screen.findByLabelText(/Mevcut parola|Current password/);
  return fetchMock;
}

function fill(current: string, next: string, confirm: string) {
  fireEvent.change(screen.getByLabelText(/Mevcut parola|Current password/), {
    target: { value: current },
  });
  fireEvent.change(screen.getByLabelText(/^(Yeni parola|New password)$/), {
    target: { value: next },
  });
  fireEvent.change(screen.getByLabelText(/(Yeni parola|New password) \((tekrar|again)\)/), {
    target: { value: confirm },
  });
  fireEvent.click(screen.getByRole("button", { name: /Parolayı değiştir|Change password/ }));
}

function callsTo(fetchMock: ReturnType<typeof mockFetch>, path: string) {
  return fetchMock.mock.calls.filter((call) => call[0] === path);
}

describe("SecuritySection password change", () => {
  it("rejects a too-short new password client-side", async () => {
    const f = await renderSection();
    fill("old-password", "abc", "abc");
    expect(await screen.findByText(/Yeni parola en az 4|The new password must be at least 4/)).toBeTruthy();
    expect(callsTo(f, "/auth/password")).toHaveLength(0);
  });

  it("rejects mismatched confirmation client-side", async () => {
    const f = await renderSection();
    fill("old-password", "long-enough-pw", "long-enough-px");
    expect(await screen.findByText(/eşleşmiyor|do not match/)).toBeTruthy();
    expect(callsTo(f, "/auth/password")).toHaveLength(0);
  });

  it("submits valid input and shows success", async () => {
    const f = await renderSection();
    fill("old-password", "long-enough-pw", "long-enough-pw");
    await waitFor(() => expect(callsTo(f, "/auth/password")).toHaveLength(1));
    expect(await screen.findByText(/Parola değiştirildi|Password changed/)).toBeTruthy();
  });

  it("shows the wrong-current-password error", async () => {
    await renderSection((url) =>
      url === "/auth/password" ? jsonResponse(401, { detail: "x", code: "invalid_password" }) : undefined,
    );
    fill("bad", "long-enough-pw", "long-enough-pw");
    expect(await screen.findByText(/Mevcut parola yanlış|current password is wrong/)).toBeTruthy();
  });
});
