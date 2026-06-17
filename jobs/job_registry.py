from __future__ import annotations

from copy import deepcopy


SUPPORTED_JOB_TYPES = {
    "paper_cycle",
    "live_dry_run",
    "healthcheck",
    "weekly_report",
    "performance_report",
    "db_status",
    "correlation_refresh",
    "memory_status",
    "readiness_check",
    "stress_test",
}


DEFAULT_JOBS = [
    {
        "job_name": "readiness_check",
        "job_type": "readiness_check",
        "handler_name": "readiness_check",
        "schedule": {"daily_at": "08:00"},
        "enabled": True,
        "config": {},
    },
    {
        "job_name": "healthcheck",
        "job_type": "healthcheck",
        "handler_name": "healthcheck",
        "schedule": {"daily_at": "08:30"},
        "enabled": True,
        "config": {},
    },
    {
        "job_name": "weekly_paper_cycle",
        "job_type": "paper_cycle",
        "handler_name": "paper_cycle",
        "schedule": {"weekly_at": {"day": "MON", "time": "09:00"}},
        "enabled": True,
        "config": {"universe": "large_cap", "max_tickers": 500, "max_trades": 5, "min_trades": 2},
    },
    {
        "job_name": "weekly_report",
        "job_type": "weekly_report",
        "handler_name": "weekly_report",
        "schedule": {"weekly_at": {"day": "FRI", "time": "16:30"}},
        "enabled": True,
        "config": {},
    },
    {
        "job_name": "performance_report",
        "job_type": "performance_report",
        "handler_name": "performance_report",
        "schedule": {"weekly_at": {"day": "FRI", "time": "16:45"}},
        "enabled": True,
        "config": {},
    },
    {
        "job_name": "stress_test",
        "job_type": "stress_test",
        "handler_name": "stress_test",
        "schedule": {"weekly_at": {"day": "FRI", "time": "17:00"}},
        "enabled": False,
        "config": {},
    },
    {
        "job_name": "db_status",
        "job_type": "db_status",
        "handler_name": "db_status",
        "schedule": {"daily_at": "08:15"},
        "enabled": True,
        "config": {},
    },
    {
        "job_name": "live_dry_run",
        "job_type": "live_dry_run",
        "handler_name": "live_dry_run",
        "schedule": {"daily_at": "08:45"},
        "enabled": False,
        "config": {"ticker": "AAPL"},
    },
    {
        "job_name": "correlation_refresh",
        "job_type": "correlation_refresh",
        "handler_name": "correlation_refresh",
        "schedule": {"daily_at": "17:00"},
        "enabled": False,
        "config": {"tickers": ["SPY", "QQQ", "AAPL", "MSFT"]},
    },
    {
        "job_name": "memory_status",
        "job_type": "memory_status",
        "handler_name": "memory_status",
        "schedule": {"daily_at": "08:20"},
        "enabled": True,
        "config": {},
    },
]


_REGISTERED_JOBS = {job["job_name"]: deepcopy(job) for job in DEFAULT_JOBS}


def register_job(
    job_name: str,
    job_type: str,
    handler_name: str,
    schedule: dict | None = None,
    enabled: bool = True,
    config: dict | None = None,
) -> dict:
    warnings: list[str] = []
    errors: list[str] = []
    if not job_name:
        errors.append("job_name is required.")
    if job_type not in SUPPORTED_JOB_TYPES:
        errors.append(f"Unsupported job_type: {job_type}")
    if not handler_name:
        errors.append("handler_name is required.")
    if errors:
        return {"ok": False, "jobs": [], "warnings": warnings, "errors": errors}
    job = {
        "job_name": str(job_name),
        "job_type": str(job_type),
        "handler_name": str(handler_name),
        "schedule": schedule or {},
        "enabled": bool(enabled),
        "config": config or {},
    }
    _REGISTERED_JOBS[job["job_name"]] = deepcopy(job)
    return {"ok": True, "jobs": [deepcopy(job)], "warnings": warnings, "errors": []}


def list_registered_jobs(config: dict | None = None) -> dict:
    jobs = [deepcopy(job) for job in _REGISTERED_JOBS.values()]
    jobs.sort(key=lambda item: item["job_name"])
    return {"ok": True, "jobs": jobs, "warnings": [], "errors": []}


def get_registered_job(job_name: str, config: dict | None = None) -> dict:
    job = _REGISTERED_JOBS.get(str(job_name))
    if not job:
        return {"ok": False, "jobs": [], "warnings": [], "errors": [f"Job not found: {job_name}"]}
    return {"ok": True, "jobs": [deepcopy(job)], "warnings": [], "errors": []}
