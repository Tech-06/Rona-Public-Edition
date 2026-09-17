import uuid

from app.config import get_settings

settings = get_settings()

PRO_NOT_CONFIGURED_ERROR = (
    "PRO model is not configured. "
    "Set PRO_MODEL, PRO_MODEL_URL and PRO_MODEL_API in the server environment."
)


async def start_subagent(task: str, tier: str) -> dict:
    from subagents import runner, store

    try:
        if tier not in ("flash", "pro"):
            return {"success": False, "error": "tier must be 'flash' or 'pro'."}
        if tier == "pro" and not settings.pro_configured:
            return {"success": False, "error": PRO_NOT_CONFIGURED_ERROR}
        if store.count_running() >= settings.subagent_max_concurrent:
            return {
                "success": False,
                "error": (
                    f"Background task limit reached ({settings.subagent_max_concurrent} "
                    "running). Wait for one to finish."
                ),
            }
        run_id = str(uuid.uuid4())
        store.create_run(run_id, task, tier)
        runner.spawn(run_id, task, tier)
        return {
            "success": True,
            "run_id": run_id,
            "status": "running",
            "tier": tier,
            "task": task,
            "hint": (
                "The task now runs in the background. Tell the user it is in "
                "progress and keep chatting normally. Do not wait for it."
            ),
        }
    except Exception as exc:  # noqa: BLE001
        return {"success": False, "error": str(exc)}


async def list_subagents(status: str = "all") -> dict:
    from subagents import store

    try:
        runs = store.list_runs(status=status)
        entries = [
            {
                "run_id": run["id"],
                "task": run["task"],
                "tier": run["tier"],
                "status": run["status"],
                "created_at": run["created_at"],
                "finished_at": run["finished_at"],
                "error": run["error"],
            }
            for run in runs
        ]
        return {"success": True, "runs": entries}
    except Exception as exc:  # noqa: BLE001
        return {"success": False, "error": str(exc)}


async def get_subagent_report(run_id: str, detail: bool = False) -> dict:
    from subagents import store

    try:
        run = store.get_run(run_id)
        if run is None:
            return {"success": False, "error": f"No background task found: {run_id}"}
        if run["status"] == "running":
            return {
                "success": True,
                "run_id": run_id,
                "status": "running",
                "task": run["task"],
            }
        payload = {
            "success": True,
            "run_id": run_id,
            "status": run["status"],
            "task": run["task"],
            "tier": run["tier"],
            "finished_at": run["finished_at"],
        }
        if run["status"] == "failed":
            payload["error"] = run["error"]
        else:
            payload["summary"] = run["summary"]
            if detail:
                payload["report"] = run["report"]
        store.mark_reported(run_id)
        return payload
    except Exception as exc:  # noqa: BLE001
        return {"success": False, "error": str(exc)}


async def dismiss_subagent_report(run_id: str) -> dict:
    from subagents import store

    try:
        run = store.get_run(run_id)
        if run is None:
            return {"success": False, "error": f"No background task found: {run_id}"}
        store.mark_reported(run_id)
        return {"success": True, "run_id": run_id, "dismissed": True}
    except Exception as exc:  # noqa: BLE001
        return {"success": False, "error": str(exc)}
