import json
import logging
import re
from datetime import datetime, timezone
from typing import Any
from zoneinfo import ZoneInfo

from apscheduler.events import EVENT_JOB_MISSED
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.date import DateTrigger

import i18n
from app.config import get_settings
from trigger import executor, store

settings = get_settings()
logger = logging.getLogger("uvicorn.error")

DATE_MISFIRE_GRACE_SECONDS = 300

UTC_ISO_FORMAT = "%Y-%m-%dT%H:%M:%SZ"

TIME_PATTERN = re.compile(r"^([0-1]?\d|2[0-3]):([0-5]\d)$")
WEEKDAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")

SCHEDULE_TYPES = ("once", "daily", "weekly", "monthly", "yearly", "cron")

_scheduler_instance: AsyncIOScheduler | None = None


def _scheduler() -> AsyncIOScheduler:
    global _scheduler_instance
    if _scheduler_instance is None:
        _scheduler_instance = AsyncIOScheduler()
        _scheduler_instance.add_listener(_on_job_missed, EVENT_JOB_MISSED)
    return _scheduler_instance


def _job_id(task_id: str, index: int) -> str:
    return f"{task_id}:{index}"


def _job_task_id(job_id: str) -> str:
    return job_id.partition(":")[0]


def _parse_time(value: Any, field: str) -> str:
    if not isinstance(value, str) or not TIME_PATTERN.match(value.strip()):
        raise ValueError(f"{field} must be in HH:MM format, got: {value!r}")
    return value.strip()


def _parse_weekdays(value: Any) -> list[str]:
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, list) or not value:
        raise ValueError("weekly schedule requires a non-empty 'weekdays' list")
    days = []
    for item in value:
        day = str(item).strip().lower()[:3]
        if day not in WEEKDAYS:
            raise ValueError(
                f"invalid weekday: {item!r} (use mon/tue/wed/thu/fri/sat/sun)"
            )
        days.append(day)
    return sorted(set(days), key=WEEKDAYS.index)


def _parse_day(value: Any, field: str) -> int:
    if not isinstance(value, int) or not 1 <= value <= 31:
        raise ValueError(f"{field} must be an integer between 1 and 31, got: {value!r}")
    return value


def _parse_month(value: Any) -> int:
    if not isinstance(value, int) or not 1 <= value <= 12:
        raise ValueError(f"month must be an integer between 1 and 12, got: {value!r}")
    return value


def _parse_iso_datetime(text: Any, default_timezone: str) -> datetime:
    if not isinstance(text, str) or not text.strip():
        raise ValueError("schedule 'at' must be an ISO 8601 datetime string")
    try:
        parsed = datetime.fromisoformat(text.strip())
    except ValueError as exc:
        raise ValueError(f"invalid ISO 8601 datetime: {text!r} ({exc})") from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=ZoneInfo(default_timezone))
    return parsed


def _to_utc_iso(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).strftime(UTC_ISO_FORMAT)


def _parse_stored_scheduled_at(text: str) -> datetime:
    return datetime.strptime(text, UTC_ISO_FORMAT).replace(tzinfo=timezone.utc)


def _parse_cron_expressions(text: str | None) -> list[str]:
    if not text:
        return []
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        return [text]
    if (
        isinstance(parsed, list)
        and parsed
        and all(isinstance(item, str) for item in parsed)
    ):
        return parsed
    return [text]


def _validate_cron(cron: str, timezone_name: str) -> None:
    try:
        CronTrigger.from_crontab(cron, timezone=timezone_name)
    except ValueError as exc:
        raise ValueError(f"invalid cron expression {cron!r}: {exc}") from exc


def derive_schedule(schedule: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(schedule, dict):
        raise TypeError("schedule must be an object")
    schedule_type = schedule.get("type")
    if schedule_type not in SCHEDULE_TYPES:
        raise ValueError(
            f"schedule type must be one of {', '.join(SCHEDULE_TYPES)}, got: {schedule_type!r}"
        )
    timezone_name = schedule.get("timezone") or settings.trigger_timezone
    try:
        ZoneInfo(timezone_name)
    except Exception as exc:
        raise ValueError(f"unknown IANA timezone: {timezone_name!r}") from exc

    if schedule_type == "once":
        moment = _parse_iso_datetime(schedule.get("at"), timezone_name)
        if moment <= datetime.now(timezone.utc):
            raise ValueError("scheduled time must be in the future")
        return {
            "is_recurring": False,
            "cron_expression": None,
            "scheduled_at": _to_utc_iso(moment),
            "timezone": timezone_name,
        }

    crons: list[str] = []
    if schedule_type == "daily":
        times = schedule.get("times")
        if isinstance(times, str):
            times = [times]
        if not isinstance(times, list) or not times:
            raise ValueError("daily schedule requires a non-empty 'times' list (HH:MM)")
        for item in times:
            time_text = _parse_time(item, "daily schedule time")
            hour, minute = time_text.split(":")
            crons.append(f"{int(minute)} {int(hour)} * * *")
    elif schedule_type == "weekly":
        days = _parse_weekdays(schedule.get("weekdays"))
        time_text = _parse_time(schedule.get("time"), "weekly schedule time")
        hour, minute = time_text.split(":")
        crons.append(f"{int(minute)} {int(hour)} * * {','.join(days)}")
    elif schedule_type == "monthly":
        day = _parse_day(schedule.get("day"), "monthly schedule day")
        time_text = _parse_time(schedule.get("time"), "monthly schedule time")
        hour, minute = time_text.split(":")
        crons.append(f"{int(minute)} {int(hour)} {day} * *")
    elif schedule_type == "yearly":
        month = _parse_month(schedule.get("month"))
        day = _parse_day(schedule.get("day"), "yearly schedule day")
        time_text = _parse_time(schedule.get("time"), "yearly schedule time")
        hour, minute = time_text.split(":")
        crons.append(f"{int(minute)} {int(hour)} {day} {month} *")
    else:
        expression = schedule.get("expression")
        if not isinstance(expression, str) or not expression.strip():
            raise ValueError("cron schedule requires a 5-field 'expression' string")
        crons = [expression.strip()]

    for cron in crons:
        _validate_cron(cron, timezone_name)

    cron_text = crons[0] if len(crons) == 1 else json.dumps(crons)
    return {
        "is_recurring": True,
        "cron_expression": cron_text,
        "scheduled_at": None,
        "timezone": timezone_name,
    }


def unregister_task(task_id: str) -> None:
    sched = _scheduler()
    prefix = f"{task_id}:"
    for job in sched.get_jobs():
        if job.id.startswith(prefix):
            sched.remove_job(job.id)


def _job_next_run(job) -> datetime | None:
    return getattr(job, "next_run_time", None)


def register_task(task: dict[str, Any]) -> datetime | None:
    sched = _scheduler()
    unregister_task(task["id"])
    if task["status"] != "active":
        return None
    timezone_name = task["timezone"]
    if task["is_recurring"]:
        next_runs = []
        for index, cron in enumerate(_parse_cron_expressions(task["cron_expression"])):
            trigger = CronTrigger.from_crontab(cron, timezone=timezone_name)
            job_id = _job_id(task["id"], index)
            sched.add_job(
                executor.fire,
                trigger,
                id=job_id,
                args=[task["id"]],
                name=task["name"],
                misfire_grace_time=None,
                coalesce=True,
                max_instances=1,
                replace_existing=True,
            )
            job = sched.get_job(job_id)
            next_fire = _job_next_run(job) if job is not None else None
            if next_fire is not None:
                next_runs.append(next_fire)
        return min(next_runs) if next_runs else None
    run_date = _parse_stored_scheduled_at(task["scheduled_at"])
    if run_date <= datetime.now(timezone.utc):
        store.finalize_past_one_shot(task["id"])
        return None
    job_id = _job_id(task["id"], 0)
    sched.add_job(
        executor.fire,
        DateTrigger(run_date=run_date),
        id=job_id,
        args=[task["id"]],
        name=task["name"],
        misfire_grace_time=DATE_MISFIRE_GRACE_SECONDS,
        coalesce=True,
        max_instances=1,
        replace_existing=True,
    )
    job = sched.get_job(job_id)
    return _job_next_run(job) if job is not None else None


def next_run_map() -> dict[str, datetime]:
    result: dict[str, datetime] = {}
    for job in _scheduler().get_jobs():
        task_id = _job_task_id(job.id)
        next_fire = _job_next_run(job)
        if next_fire is None:
            continue
        current = result.get(task_id)
        if current is None or next_fire < current:
            result[task_id] = next_fire
    return result


def _on_job_missed(event) -> None:
    task_id = _job_task_id(event.job_id)
    try:
        task = store.get_task(task_id)
        if task is None:
            return
        if task["is_recurring"]:
            return
        store.finalize_past_one_shot(task_id)
        logger.warning(i18n.t("trigger.log_missed"), task_id[:8], task["name"])
    except Exception as exc:  # noqa: BLE001
        logger.error(i18n.t("trigger.log_missed_event_failed"), task_id[:8], exc)


def register_all_from_db() -> int:
    try:
        tasks = store.list_tasks("active")
    except FileNotFoundError:
        logger.info(i18n.t("trigger.log_db_not_found"))
        return 0
    registered = 0
    for task in tasks:
        try:
            next_run = register_task(task)
        except Exception as exc:  # noqa: BLE001
            logger.error(
                i18n.t("trigger.log_register_failed"),
                task["id"][:8],
                task["name"],
                exc,
            )
            continue
        if next_run is not None:
            registered += 1
    logger.info(i18n.t("trigger.log_scheduled_count"), registered)
    return registered


def is_running() -> bool:
    return _scheduler_instance is not None and _scheduler_instance.running


def start() -> None:
    sched = _scheduler()
    if not sched.running:
        sched.start()
    register_all_from_db()


def shutdown() -> None:
    global _scheduler_instance
    if _scheduler_instance is not None and _scheduler_instance.running:
        _scheduler_instance.shutdown(wait=False)
    _scheduler_instance = None
