import { api } from "./client";

// Wire shapes for the BFF's own package-job endpoints
// (web-client/webui/package_jobs.py). These never go through the /api reverse-proxy path -- the
// browser talks to the BFF directly, exactly like the existing
// /host/server* calls in dashboard.ts (serverStatus/serverAction). That's
// deliberate: install/update/uninstall run `pip`/`git` subprocesses that
// can take far longer than the backend's own 45s proxy read timeout, and
// the BFF (unlike the backend) never restarts itself mid-install.

export interface HostPackageEntry {
  id: string;
  version: string;
  name: string;
  description: string;
  kind: "tool" | "library";
  /** Raw, unparsed requirement strings (e.g. "google_auth>=2.0"), or null
   * for a package with no dependencies. Never parsed client-side -- shown
   * as-is, same as the CLI does. */
  requires: string[] | null;
  installed: boolean;
  installed_version: string | null;
  update_available: boolean;
}

export interface HostPackagesAvailable {
  ok: true;
  packages: HostPackageEntry[];
  fetched_at: number;
}

export type PlanReason = "requested" | "dependency" | "upgrade";

export interface PlanEntry {
  id: string;
  name: string;
  version: string;
  kind: "tool" | "library";
  reason: PlanReason;
  already_installed: boolean;
  installed_version: string | null;
  needs_action: boolean;
}

export interface HostPackagePlan {
  ok: true;
  package: string;
  action: "install" | "update";
  up_to_date: boolean;
  complete: boolean;
  entries: PlanEntry[];
}

export type PackageJobAction = "install" | "update" | "uninstall";
export type PackageJobState = "running" | "succeeded" | "failed";

export interface PackageHealthResult {
  ok: boolean;
  detail: string;
}

/** The manager CLI's own JSON result (`python -m toolbox.manager --json`), handed back
 * unchanged as `job.result` once the subprocess finishes. Every field
 * below is optional because the "already up to date" shorthand result
 * only carries a subset of them. */
export interface PackageJobResult {
  ok?: boolean;
  installed?: string[];
  upgraded?: Array<{ id: string; from: string; to: string }>;
  config_pending?: Record<string, string[]>;
  health?: Record<string, PackageHealthResult>;
  restart_recommended?: boolean;
  restored?: string[];
  note?: string;
  up_to_date?: boolean;
  package?: string;
  version?: string;
}

export interface PackageJob {
  id: string;
  action: PackageJobAction;
  package_id: string;
  state: PackageJobState;
  started_at: number;
  finished_at: number | null;
  log_lines: string[];
  result: PackageJobResult | null;
  error: string | null;
}

export const hostPackagesApi = {
  available: (refresh = false) =>
    api.get<HostPackagesAvailable>(`/host/packages/available${refresh ? "?refresh=1" : ""}`),
  plan: (id: string) => api.get<HostPackagePlan>(`/host/packages/plan/${id}`),
  install: (id: string) =>
    api.post<{ job: PackageJob }>("/host/packages/install", { package_id: id }),
  update: (id: string) =>
    api.post<{ job: PackageJob }>("/host/packages/update", { package_id: id }),
  uninstall: (id: string, purge: boolean) =>
    api.post<{ job: PackageJob }>("/host/packages/uninstall", { package_id: id, purge }),
  job: () => api.get<{ job: PackageJob | null }>("/host/packages/job"),
};
