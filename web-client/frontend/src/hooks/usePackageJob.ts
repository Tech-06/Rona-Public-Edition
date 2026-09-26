import { useCallback, useEffect, useRef, useState } from "react";
import { ApiError } from "../api/client";
import { hostPackagesApi, type PackageJob, type PackageJobAction } from "../api/hostPackages";

const HANDLED_KEY = "rona:pkgjob:handled";
const DISMISSED_KEY = "rona:pkgjob:dismissed";
const POLL_INTERVAL_MS = 1000;
// A job that had already finished this long before this tab ever saw it is
// old news: don't pop its panel up or re-run the post-job refresh for it.
const STALE_FINISHED_SECONDS = 600;

function readKey(key: string): string | null {
  try {
    return sessionStorage.getItem(key);
  } catch {
    return null;
  }
}

function writeKey(key: string, id: string): void {
  try {
    sessionStorage.setItem(key, id);
  } catch {
    // storage unavailable (private mode, quota) -- onFinished may run
    // again on a later remount, which is harmless (reload + refresh are
    // idempotent), just redundant.
  }
}

/** Tracks the single package install/update/uninstall job the BFF runs
 * (web-client/webui/package_jobs.py). The job itself lives in the BFF's
 * memory, not this component's state, so mounting this hook anywhere --
 * even after the settings modal was closed and reopened -- picks the same
 * job back up via `GET /host/packages/job`.
 *
 * `onFinished` fires exactly once per job id even across remounts: the id
 * of the last job this browser tab has already reacted to is kept in
 * sessionStorage, so closing and reopening the settings modal while an
 * install runs still triggers the post-job refresh (reload, connections
 * refetch, ...) exactly once, whenever a mounted ConnectionsPanel next
 * notices the job reached a terminal state. The BFF keeps its last finished
 * job around indefinitely, so a dismissed job's id is remembered too, or it
 * would reappear every time the section is reopened. */
export function usePackageJob(onFinished: (job: PackageJob) => void) {
  const [job, setJob] = useState<PackageJob | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const jobRef = useRef<PackageJob | null>(null);
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const pollRef = useRef<() => Promise<void>>(async () => {});
  const onFinishedRef = useRef(onFinished);
  onFinishedRef.current = onFinished;

  const show = useCallback((value: PackageJob | null) => {
    jobRef.current = value;
    setJob(value);
  }, []);

  const clearTimer = useCallback(() => {
    if (timerRef.current !== null) {
      clearTimeout(timerRef.current);
      timerRef.current = null;
    }
  }, []);

  const schedule = useCallback(() => {
    clearTimer();
    timerRef.current = setTimeout(() => void pollRef.current(), POLL_INTERVAL_MS);
  }, [clearTimer]);

  const poll = useCallback(async () => {
    let current: PackageJob | null;
    try {
      current = (await hostPackagesApi.job()).job;
      setError(null);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : String(err));
      // A network blip mid-job must not stop the polling for good.
      if (jobRef.current?.state === "running") schedule();
      return;
    }

    if (current === null) {
      show(null);
      return;
    }
    if (current.state === "running") {
      show(current);
      schedule();
      return;
    }
    if (readKey(HANDLED_KEY) === current.id) {
      // Already reacted to in this tab: keep it on screen until dismissed.
      show(readKey(DISMISSED_KEY) === current.id ? null : current);
      return;
    }

    writeKey(HANDLED_KEY, current.id);
    const finishedLongAgo =
      current.finished_at !== null && Date.now() / 1000 - current.finished_at > STALE_FINISHED_SECONDS;
    if (finishedLongAgo && jobRef.current === null) {
      writeKey(DISMISSED_KEY, current.id);
      return;
    }
    show(current);
    onFinishedRef.current(current);
  }, [schedule, show]);
  pollRef.current = poll;

  useEffect(() => {
    void pollRef.current();
    return clearTimer;
  }, [clearTimer]);

  const start = useCallback(
    async (action: PackageJobAction, id: string, purge?: boolean) => {
      setSubmitting(true);
      setError(null);
      try {
        const response =
          action === "install"
            ? await hostPackagesApi.install(id)
            : action === "update"
              ? await hostPackagesApi.update(id)
              : await hostPackagesApi.uninstall(id, Boolean(purge));
        show(response.job);
        if (response.job.state === "running") schedule();
        else void pollRef.current();
        return response.job;
      } catch (err) {
        const message = err instanceof ApiError ? err.message : String(err);
        setError(message);
        throw err;
      } finally {
        setSubmitting(false);
      }
    },
    [schedule, show],
  );

  const dismiss = useCallback(() => {
    if (jobRef.current) writeKey(DISMISSED_KEY, jobRef.current.id);
    show(null);
  }, [show]);

  return {
    job,
    start,
    dismiss,
    // True while a start() request is in flight, or while the last known
    // job is still running server-side -- either way, another
    // install/update/uninstall must not be kicked off right now (the
    // manager itself only allows one at a time; this just makes the UI
    // reflect that instead of letting the person hit a 409).
    busy: submitting || job?.state === "running",
    error,
  };
}
