import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { readLocale } from "./i18n";

function setMeta(content: string | null) {
  document.querySelectorAll('meta[name="rona-lang"]').forEach((m) => m.remove());
  if (content === null) return;
  const meta = document.createElement("meta");
  meta.name = "rona-lang";
  meta.content = content;
  document.head.appendChild(meta);
}

// The test env's localStorage isn't reliably available, so use a plain map.
beforeEach(() => {
  const store = new Map<string, string>();
  vi.stubGlobal("localStorage", {
    getItem: (k: string) => store.get(k) ?? null,
    setItem: (k: string, v: string) => void store.set(k, v),
  });
});

afterEach(() => {
  vi.unstubAllGlobals();
  setMeta(null);
  delete (window as unknown as { __RONA_LANG__?: string }).__RONA_LANG__;
});

describe("readLocale server default", () => {
  it("reads the rona-lang meta tag", () => {
    setMeta("en");
    expect(readLocale()).toBe("en");
  });

  it("falls back to window.__RONA_LANG__", () => {
    (window as unknown as { __RONA_LANG__?: string }).__RONA_LANG__ = "en";
    expect(readLocale()).toBe("en");
  });

  it("ignores an invalid meta value", () => {
    setMeta("de");
    expect(readLocale()).toBe("tr");
  });

  it("prefers the viewer's stored choice over the meta tag", () => {
    setMeta("en");
    localStorage.setItem("rona:lang", "tr");
    expect(readLocale()).toBe("tr");
  });
});
