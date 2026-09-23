import { useEffect, useRef } from "react";
import { migrateLegacyLocalHistory, syncFromServer } from "../lib/storage";

const SYNC_INTERVAL_MS = 30_000;
// Coming back to the app (focus, tab/app switch, a phone restoring the
// page from its back/forward cache) syncs right away -- that is exactly
// when a conversation continued on another device should show up. This
// only keeps the handful of events one return fires from each triggering
// its own request.
const RETURN_SYNC_MIN_GAP_MS = 2_000;

/** Keeps the local conversation cache (lib/storage.ts) in step with the
 * server-side history (backend/graph/history.py), the single source of
 * truth every device shares.
 *
 * On mount, first runs the one-time legacy-localStorage migration (a no-op
 * once this browser's old history has been uploaded), then does an initial
 * sync. After that it re-syncs every SYNC_INTERVAL_MS while the page is
 * visible, and immediately whenever the user comes back to it. An open
 * conversation picks the result up on its own (see useChat.ts).
 *
 * Network failures are swallowed throughout -- this is background
 * housekeeping, not something that should surface an error to the user;
 * it just tries again on the next tick.
 */
export function useConversationSync(onSynced: () => void): void {
  const onSyncedRef = useRef(onSynced);
  onSyncedRef.current = onSynced;

  useEffect(() => {
    let cancelled = false;
    let started = false;
    let lastSyncAt = 0;

    async function sync(minGapMs: number) {
      if (!started) return;
      const now = Date.now();
      if (now - lastSyncAt < minGapMs) return;
      lastSyncAt = now;
      try {
        await syncFromServer();
        if (cancelled) return;
        onSyncedRef.current();
      } catch {
        // backend unreachable or erroring - skip this cycle, retry later
      }
    }

    async function start() {
      try {
        await migrateLegacyLocalHistory();
      } catch {
        // never block the first sync on a failed migration attempt --
        // it's retried on the next start
      }
      if (cancelled) return;
      started = true;
      await sync(0);
    }

    start();
    const interval = setInterval(() => {
      if (document.visibilityState === "visible") sync(RETURN_SYNC_MIN_GAP_MS);
    }, SYNC_INTERVAL_MS);
    function handleReturn() {
      if (document.visibilityState === "visible") sync(RETURN_SYNC_MIN_GAP_MS);
    }
    window.addEventListener("focus", handleReturn);
    window.addEventListener("pageshow", handleReturn);
    document.addEventListener("visibilitychange", handleReturn);
    return () => {
      cancelled = true;
      clearInterval(interval);
      window.removeEventListener("focus", handleReturn);
      window.removeEventListener("pageshow", handleReturn);
      document.removeEventListener("visibilitychange", handleReturn);
    };
    // Mount-once: onSynced is read through a ref so the interval/listeners
    // never need to be torn down and rebuilt.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
}
