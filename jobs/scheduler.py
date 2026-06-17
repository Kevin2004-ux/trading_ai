from __future__ import annotations

import os
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from .job_registry import list_registered_jobs


DAY_INDEX = {"MON": 0, "TUE": 1, "WED": 2, "THU": 3, "FRI": 4, "SAT": 5, "SUN": 6}
TRUE_VALUES = {"1", "true", "yes", "y", "on"}


def _bool_value(value: object, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in TRUE_VALUES


def _tz(schedule: dict | None = None) -> ZoneInfo:
    name = (schedule or {}).get("timezone") or os.getenv("SCHEDULER_TIMEZONE") or "America/New_York"
    try:
        return ZoneInfo(str(name))
    except Exception:
        return ZoneInfo("America/New_York")


def _parse_now(now: str | None, schedule: dict | None = None) -> datetime:
    tz = _tz(schedule)
    if now:
        text = str(now)
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        parsed = datetime.fromisoformat(text)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=tz)
        return parsed.astimezone(tz)
    return datetime.now(tz)


def _parse_time(value: str) -> tuple[int, int]:
    hour, minute = str(value or "00:00").split(":", 1)
    return int(hour), int(minute)


def _market_day(dt: datetime) -> bool:
    return dt.weekday() < 5


def calculate_next_run(
    schedule: dict,
    now: str | None = None,
) -> dict:
    if not isinstance(schedule, dict):
        return {"ok": False, "next_run": None, "errors": ["Schedule must be a dict."]}
    current = _parse_now(now, schedule)
    market_days_only = _bool_value(
        schedule.get("market_days_only"),
        default=_bool_value(os.getenv("SCHEDULER_MARKET_DAYS_ONLY", "true"), default=True),
    )

    if schedule.get("interval_minutes"):
        minutes = max(int(schedule["interval_minutes"]), 1)
        candidate = current + timedelta(minutes=minutes)
    elif schedule.get("daily_at"):
        hour, minute = _parse_time(schedule["daily_at"])
        candidate = current.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if candidate <= current:
            candidate += timedelta(days=1)
    elif schedule.get("weekly_at"):
        weekly = schedule["weekly_at"] if isinstance(schedule["weekly_at"], dict) else {}
        day = str(weekly.get("day", "MON")).upper()[:3]
        hour, minute = _parse_time(weekly.get("time", "09:00"))
        target_weekday = DAY_INDEX.get(day, 0)
        days_ahead = (target_weekday - current.weekday()) % 7
        candidate = (current + timedelta(days=days_ahead)).replace(hour=hour, minute=minute, second=0, microsecond=0)
        if candidate <= current:
            candidate += timedelta(days=7)
    else:
        return {"ok": False, "next_run": None, "errors": ["Unsupported schedule."]}

    if market_days_only:
        while not _market_day(candidate):
            candidate += timedelta(days=1)
            candidate = candidate.replace(hour=candidate.hour, minute=candidate.minute, second=0, microsecond=0)
    return {"ok": True, "next_run": candidate.isoformat(), "timezone": str(current.tzinfo), "errors": []}


def should_run_job(
    job: dict,
    now: str | None = None,
) -> dict:
    if not isinstance(job, dict):
        return {"ok": False, "should_run": False, "reason": "Job must be a dict.", "errors": ["Job must be a dict."]}
    if not job.get("enabled", True):
        return {"ok": True, "should_run": False, "reason": "Job is disabled.", "errors": []}
    schedule = job.get("schedule") if isinstance(job.get("schedule"), dict) else {}
    current = _parse_now(now, schedule)
    last_run = job.get("last_run_at")
    if not last_run:
        return {"ok": True, "should_run": True, "reason": "Job has never run.", "errors": []}
    next_run = calculate_next_run(schedule, now=last_run)
    if not next_run.get("ok"):
        return {"ok": False, "should_run": False, "reason": "Invalid schedule.", "errors": next_run.get("errors", [])}
    due_at = _parse_now(next_run["next_run"], schedule)
    return {"ok": True, "should_run": current >= due_at, "next_run": next_run["next_run"], "reason": "Due" if current >= due_at else "Not due.", "errors": []}


def build_default_schedule(config: dict | None = None) -> dict:
    supplied = config if isinstance(config, dict) else {}
    timezone = supplied.get("SCHEDULER_TIMEZONE") or os.getenv("SCHEDULER_TIMEZONE", "America/New_York")
    paper_day = supplied.get("DEFAULT_PAPER_SCAN_DAY") or os.getenv("DEFAULT_PAPER_SCAN_DAY", "MON")
    paper_time = supplied.get("DEFAULT_PAPER_SCAN_TIME") or os.getenv("DEFAULT_PAPER_SCAN_TIME", "09:00")
    health_time = supplied.get("DEFAULT_HEALTHCHECK_TIME") or os.getenv("DEFAULT_HEALTHCHECK_TIME", "08:30")
    jobs = list_registered_jobs().get("jobs", [])
    return {
        "ok": True,
        "scheduler_enabled": _bool_value(supplied.get("SCHEDULER_ENABLED"), default=_bool_value(os.getenv("SCHEDULER_ENABLED", "false"))),
        "timezone": timezone,
        "market_days_only": _bool_value(supplied.get("SCHEDULER_MARKET_DAYS_ONLY"), default=_bool_value(os.getenv("SCHEDULER_MARKET_DAYS_ONLY", "true"), default=True)),
        "defaults": {
            "paper_cycle": {"weekly_at": {"day": paper_day, "time": paper_time}, "timezone": timezone},
            "healthcheck": {"daily_at": health_time, "timezone": timezone},
        },
        "jobs": jobs,
        "warnings": [] if jobs else ["No jobs registered."],
        "errors": [],
    }
