import { describe, expect, it } from "vitest";
import source from "../../public/sw.js?raw";

// There is no service-worker test harness, so assert on the source: the
// offline page's external scripts must be precached AND served by the fetch
// handler, or they 404 offline and the Retry button is dead.

describe("service worker", () => {
  it("precaches the offline page and its scripts", () => {
    const list = /PRECACHE_URLS = \[([^\]]*)\]/.exec(source)?.[1] ?? "";
    expect(list).toContain("OFFLINE_URL");
    expect(list).toContain('"/offline.js"');
    expect(list).toContain('"/theme-init.js"');
  });

  it("serves precached same-origin GETs network-first with a cache fallback", () => {
    expect(source).toContain("PRECACHE_URLS.includes(url.pathname)");
    expect(source).toContain('request.method !== "GET"');
    expect(source).toMatch(/fetch\(event\.request\)\.catch\(/);
  });

  it("refreshes every precached entry and uses a bumped cache name", () => {
    expect(source).toContain("PRECACHE_URLS.map((url) => cache.add(");
    expect(source).not.toContain('"rona-offline-v2"');
  });
});
