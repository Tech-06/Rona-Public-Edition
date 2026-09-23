// Rona's service worker. Its ONLY job is the offline fallback page -- it
// never caches the app shell, the JS/CSS bundle, or any API response.
//
// That's deliberate, not an oversight: this app's whole point is showing
// live, shared, server-side state (backend/graph/history.py's chat
// history first among it). A service worker that cached any of that would
// reintroduce, inside the installed app, exactly the "browser served a
// stale build/data" problem the web client's Cache-Control: no-cache on
// index.html (see webui/server.py) and `cache: "no-store"` on every API
// request (see src/api/client.ts) already exist to prevent. So: every
// non-navigation request (api/client.ts's fetches, /chat/stream's SSE,
// /assets/*, /host/*) is left alone entirely, and a navigation always
// tries the network first, only ever falling back to the cached
// offline.html when the network is unreachable.

const CACHE_NAME = "rona-offline-v1";
const OFFLINE_URL = "/offline.html";
const PRECACHE_URLS = [OFFLINE_URL, "/favicon.svg"];

self.addEventListener("install", (event) => {
  event.waitUntil(
    caches
      .open(CACHE_NAME)
      .then((cache) =>
        cache.addAll(PRECACHE_URLS.map((url) => new Request(url, { cache: "reload" }))),
      )
      .then(() => self.skipWaiting()),
  );
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches
      .keys()
      .then((keys) => Promise.all(keys.filter((key) => key !== CACHE_NAME).map((key) => caches.delete(key))))
      .then(() => self.clients.claim()),
  );
});

function refreshOfflinePage() {
  // Best-effort, off the response path: keeps the cached fallback from
  // drifting out of sync with a redeployed offline.html even though sw.js
  // itself didn't change (a byte-for-byte identical sw.js never triggers
  // the browser's own update-and-reinstall check).
  caches
    .open(CACHE_NAME)
    .then((cache) => cache.add(new Request(OFFLINE_URL, { cache: "reload" })))
    .catch(() => {});
}

self.addEventListener("fetch", (event) => {
  if (event.request.mode !== "navigate") return; // everything else: not our concern

  event.respondWith(
    fetch(event.request).then(
      (response) => {
        refreshOfflinePage();
        return response;
      },
      () => caches.match(OFFLINE_URL).then((cached) => cached ?? Response.error()),
    ),
  );
});
