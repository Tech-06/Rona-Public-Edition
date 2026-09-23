import { useEffect, useRef } from "react";
import { migrateLegacyLocalHistory, syncFromServer } from "../lib/storage";

const SYNC_INTERVAL_MS = 30_000;

/** Keeps the local conversation cache (lib/storage.ts) in step with the
 * server-side history (backend/graph/history.py), which is now the single
 * source of truth shared by every device.
 *
 * On mount, first runs the one-time legacy-localStorage migration (a no-op
 * once a browser's old per-origin history has already been uploaded), then
 * does an initial sync. After that it re-syncs periodically and on
 * focus/visibility, the same cadence the old TTL-purge-reconciliation
 * version of this hook used, so a conversation finished on another device
 * (or by a backgrounded phone app whose turn kept running server-side)
 * shows up here without a manual reload.
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
    let lastSyncAt = 0;

    async function sync(force = false) {
      const now = Date.now();
      if (!force && now - lastSyncAt < SYNC_INTERVAL_MS) return;
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
        // never block the first sync on a failed migration attempt
      }
      if (cancelled) return;
      await sync(true);
    }

    start();
    const interval = setInterval(() => sync(), SYNC_INTERVAL_MS);
    function handleFocus() {
      sync();
    }
    function handleVisibility() {
      if (document.visibilityState === "visible") sync();
    }
    window.addEventListener("focus", handleFocus);
    document.addEventListener("visibilitychange", handleVisibility);
    return () => {
      cancelled = true;
      clearInterval(interval);
      window.removeEventListener("focus", handleFocus);
      document.removeEventListener("visibilitychange", handleVisibility);
    };
    // Mount-once: onSynced is read through a ref so the interval/listeners
    // never need to be torn down and rebuilt.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
}
