import { useEffect, useRef } from "react";
import { dashboardApi } from "../api/dashboard";
import { removePurgedConversations } from "../lib/storage";

const SYNC_INTERVAL_MS = 30_000;

/** Periodically reconciles local conversation storage against the
 * backend's TTL purge, closing the loop the user asked for: "sohbet
 * sunucudan silinirse (timeout), web arayüzünden de silinsin."
 *
 * Deliberately conservative, on purpose:
 * - Only ever deletes ids the server explicitly lists in `purged`. A
 *   conversation being merely ABSENT from the server's active list is
 *   NOT evidence it was deleted (fresh rona.db, a restart before
 *   reconcile, rona_checkpoints.db reset, ...) - treating absence as
 *   deletion would wipe the user's only copy of a transcript on nothing
 *   more than a timing coincidence.
 * - Never removes `activeConversationId` - this hook can't know whether
 *   a turn is in flight, so the conversation the user is currently
 *   looking at is left alone even if it's in `purged`; it gets cleaned
 *   up on a later sync once it's no longer active.
 * - Never touches local `pinned` state. Pin is synced the other
 *   direction, optimistically, at the point of the user's action (see
 *   ConversationRow's togglePin) - overwriting it here on every poll
 *   would silently revert a pin the moment a racing POST hadn't landed
 *   yet server-side.
 *
 * Network failures (backend down, unreachable) are swallowed - this is
 * background housekeeping, not something that should ever surface an
 * error to the user; it just tries again on the next tick.
 */
export function useConversationSync(activeConversationId: string | null, onSynced: () => void): void {
  const activeRef = useRef(activeConversationId);
  activeRef.current = activeConversationId;
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
        const result = await dashboardApi.serverConversations();
        if (cancelled) return;
        const purged = result.purged.filter((id) => id !== activeRef.current);
        removePurgedConversations(purged);
        onSyncedRef.current();
      } catch {
        // backend unreachable or erroring - skip this cycle, retry later
      }
    }

    sync(true);
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
    // Mount-once: activeConversationId/onSynced are read through refs so
    // the interval/listeners never need to be torn down and rebuilt.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
}
