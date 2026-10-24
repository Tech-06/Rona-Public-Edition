import { afterEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import type { PackageStatus } from "../../api/dashboard";
import { jsonResponse, mockFetch } from "../../test/mockFetch";
import { LanguageProvider } from "../LanguageProvider";
import { PackagePanel } from "./ConnectionsPanel";

afterEach(() => {
  vi.unstubAllGlobals();
});

const pkg = {
  id: "gcal",
  name: "gcal",
  actions: [],
} as unknown as PackageStatus;

const fields = [
  {
    key: "credentials",
    label: "Credentials file",
    description: "",
    type: "string",
    target: "file",
    secret: false,
    required: true,
    set: false,
  },
];

describe("PackagePanel file fields", () => {
  it("renders a file input and uploads the chosen file as base64 JSON", async () => {
    const calls: { url: string; init?: RequestInit }[] = [];
    mockFetch((url, init) => {
      calls.push({ url, init });
      if (url.endsWith("/config/file")) return jsonResponse(200, { ok: true, field: "credentials" });
      return jsonResponse(200, { id: "gcal", fields });
    });

    const { container } = render(
      <LanguageProvider>
        <PackagePanel pkg={pkg} onChanged={() => {}} />
      </LanguageProvider>,
    );
    await screen.findByText("Credentials file");
    const input = container.querySelector('input[type="file"]') as HTMLInputElement;
    expect(input).not.toBeNull();
    expect(container.querySelector('input[type="text"]')).toBeNull();

    const body = '{"installed":{"client_id":"x"}}';
    fireEvent.change(input, {
      target: { files: [new File([body], "client.json", { type: "application/json" })] },
    });

    await waitFor(() => expect(calls.some((c) => c.url.endsWith("/config/file"))).toBe(true));
    const post = calls.find((c) => c.url.endsWith("/config/file"))!;
    expect(post.url).toBe("/api/packages/gcal/config/file");
    expect(post.init?.method).toBe("POST");
    expect((post.init?.headers as Record<string, string>)["Content-Type"]).toBe("application/json");
    const sent = JSON.parse(String(post.init?.body));
    expect(sent.key).toBe("credentials");
    expect(sent.filename).toBe("client.json");
    expect(atob(sent.content_b64)).toBe(body);
  });

  it("keeps unsaved edits to other fields when a file upload refreshes the config", async () => {
    const mixed = [
      { ...fields[0] },
      {
        key: "calendar_name",
        label: "Calendar name",
        description: "",
        type: "string",
        target: "env",
        secret: false,
        required: false,
        set: false,
      },
    ];
    mockFetch((url) => {
      if (url.endsWith("/config/file")) return jsonResponse(200, { ok: true, field: "credentials" });
      return jsonResponse(200, { id: "gcal", fields: mixed });
    });

    const { container } = render(
      <LanguageProvider>
        <PackagePanel pkg={pkg} onChanged={() => {}} />
      </LanguageProvider>,
    );
    await screen.findByText("Calendar name");
    const text = container.querySelector('input[type="text"]') as HTMLInputElement;
    fireEvent.change(text, { target: { value: "Work" } });
    expect(text.value).toBe("Work");

    const input = container.querySelector('input[type="file"]') as HTMLInputElement;
    fireEvent.change(input, {
      target: { files: [new File(["{}"], "client.json", { type: "application/json" })] },
    });
    // The restart notice appears right after the upload (and before the refresh
    // finishes), so wait for the refresh request to have landed too.
    await waitFor(() => expect(container.querySelector("p.text-warn-text")).not.toBeNull());
    await new Promise((resolve) => setTimeout(resolve, 50));
    await waitFor(() => {
      const refreshed = container.querySelector('input[type="text"]') as HTMLInputElement;
      expect(refreshed.value).toBe("Work");
    });
  });
});
