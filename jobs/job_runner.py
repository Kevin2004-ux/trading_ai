from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from alerts.alert_manager import process_alerts
from alerts.alert_rules import evaluate_alert_rules
from db.audit_log import append_audit_event
from db.schema_manager import get_schema_version, validate_schema
from diagnostics.healthcheck import check_environment
from diagnostics.live_dry_run import run_provider_dry_run
from memory.vector_memory import get_memory_config
from realtime.market_data import get_historical_bars
from reports.report_generator import generate_full_paper_trading_report, generate_performance_diagnostics_report
from risk.correlation_matrix import refresh_correlation_snapshot
from simulation.scenario_runner import run_default_stress_suite

from .job_history import record_job_run
from .job_registry import get_registered_job, list_registered_jobs
from .paper_jobs import run_weekly_paper_cycle_job
from .scheduler import should_run_job


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _status(result: dict) -> str:
    if result.get("skipped"):
        return "skipped"
    if result.get("ok") is False:
        return "failed"
    if result.get("warnings") or result.get("warning"):
        return "warning"
    return "success"


def _run_handler(job: dict, db_path: str, dry_run: bool, config: dict | None) -> dict:
    handler = job.get("handler_name")
    job_config = {**(job.get("config") if isinstance(job.get("config"), dict) else {}), **(config or {})}
    if handler == "paper_cycle":
        if dry_run:
            return {"ok": True, "dry_run": True, "skipped": False, "message": "Dry run: paper cycle was not executed.", "summary": {"selected_count": 0}}
        return run_weekly_paper_cycle_job(db_path=db_path, **{key: value for key, value in job_config.items() if key in {"universe", "max_tickers", "max_trades", "min_trades"}})
    if handler == "live_dry_run":
        return run_provider_dry_run(
            ticker=job_config.get("ticker", "AAPL"),
            include_market_data=not dry_run,
            include_news=False,
            include_sec_filings=False,
            include_earnings_transcripts=False,
            include_options=False,
            include_memory=False,
            db_path=db_path,
        )
    if handler == "healthcheck":
        return check_environment(db_path=db_path)
    if handler == "readiness_check":
        from config.runtime_readiness import check_runtime_readiness

        return check_runtime_readiness({"DATABASE_PATH": db_path}, include_live_checks=False)
    if handler == "weekly_report":
        return generate_full_paper_trading_report(db_path=db_path, format="dict")
    if handler == "performance_report":
        return generate_performance_diagnostics_report(db_path=db_path, format="dict")
    if handler == "stress_test":
        return run_default_stress_suite(
            trading_result=job_config.get("trading_result"),
            config={**job_config, "db_path": db_path},
        )
    if handler == "db_status":
        validation = validate_schema(db_path=db_path)
        version = get_schema_version(db_path=db_path)
        return {"ok": bool(validation.get("ok")) and bool(version.get("ok")), "validation": validation, "schema_version": version, "errors": list(validation.get("errors", []))}
    if handler == "correlation_refresh":
        if dry_run:
            return {"ok": True, "dry_run": True, "skipped": False, "message": "Dry run: correlation refresh was not executed.", "warnings": []}
        return refresh_correlation_snapshot(
            db_path=db_path,
            tickers=job_config.get("tickers", ["SPY", "QQQ"]),
            price_history_provider=lambda ticker, lookback_days: get_historical_bars(ticker, lookback_days=lookback_days),
            lookback_days=int(job_config.get("lookback_days", 60)),
        )
    if handler == "memory_status":
        memory_config = get_memory_config()
        return {"ok": True, "memory_config": {key: value for key, value in memory_config.items() if key != "pinecone_api_key"}, "warnings": list(memory_config.get("warnings", []))}
    return {"ok": False, "error": f"Unsupported handler: {handler}", "errors": [f"Unsupported handler: {handler}"]}


def run_registered_job(
    job_name: str,
    db_path: str | None = None,
    dry_run: bool = True,
    config: dict | None = None,
) -> dict:
    resolved_db_path = db_path or "strategy_library.db"
    lookup = get_registered_job(job_name)
    if not lookup.get("ok"):
        return {
            "ok": False,
            "job_name": job_name,
            "job_type": None,
            "status": "failed",
            "started_at": _now_iso(),
            "completed_at": _now_iso(),
            "duration_seconds": 0.0,
            "result": None,
            "alerts": [],
            "warnings": [],
            "errors": lookup.get("errors", []),
        }
    job = lookup["jobs"][0]
    started_at = _now_iso()
    start_monotonic = time.monotonic()
    job_run_id = f"job_run:{uuid4().hex}"
    append_audit_event(resolved_db_path, "scheduled_job_started", {"job_name": job["job_name"], "dry_run": dry_run}, run_id=job_run_id, entity_type="scheduled_job", entity_id=job["job_name"])
    warnings: list[str] = []
    errors: list[str] = []
    try:
        result = _run_handler(job, resolved_db_path, dry_run=dry_run, config=config)
    except Exception as exc:
        result = {"ok": False, "error": str(exc), "errors": [str(exc)]}
    completed_at = _now_iso()
    duration_seconds = round(time.monotonic() - start_monotonic, 4)
    status = _status(result if isinstance(result, dict) else {"ok": False})
    if isinstance(result, dict):
        warnings.extend(str(item) for item in result.get("warnings", []) if item) if isinstance(result.get("warnings"), list) else None
        if result.get("warning"):
            warnings.append(str(result["warning"]))
        errors.extend(str(item) for item in result.get("errors", []) if item) if isinstance(result.get("errors"), list) else None
        if result.get("error") and not errors:
            errors.append(str(result["error"]))
    job_result = {
        "ok": status in {"success", "warning", "skipped"},
        "job_run_id": job_run_id,
        "job_name": job["job_name"],
        "job_type": job["job_type"],
        "status": status,
        "started_at": started_at,
        "completed_at": completed_at,
        "duration_seconds": duration_seconds,
        "dry_run": bool(dry_run),
        "result": result,
        "alerts": [],
        "warnings": warnings,
        "errors": errors,
    }
    alert_eval = evaluate_alert_rules(job_result=job_result, trading_result=result if job["job_type"] == "paper_cycle" else None, health_result=result if job["job_type"] in {"healthcheck", "readiness_check", "live_dry_run", "db_status"} else None)
    alert_process = process_alerts(resolved_db_path, alert_eval.get("alerts", []), config=config)
    job_result["alerts"] = alert_process.get("stored_alerts", [])
    record_job_run(
        db_path=resolved_db_path,
        job_run_id=job_run_id,
        job_name=job["job_name"],
        job_type=job["job_type"],
        status=status,
        started_at=started_at,
        completed_at=completed_at,
        duration_seconds=duration_seconds,
        dry_run=dry_run,
        result=result if isinstance(result, dict) else {},
        warnings=warnings,
        errors=errors,
    )
    append_audit_event(
        resolved_db_path,
        "scheduled_job_failed" if status == "failed" else "scheduled_job_completed",
        {"job_name": job["job_name"], "status": status, "alerts": len(job_result["alerts"])},
        run_id=job_run_id,
        entity_type="scheduled_job",
        entity_id=job["job_name"],
    )
    for alert in job_result["alerts"]:
        append_audit_event(resolved_db_path, "alert_created", alert, run_id=job_run_id, entity_type="alert", entity_id=alert.get("alert_id"))
    return job_result


def run_due_jobs(
    db_path: str | None = None,
    now: str | None = None,
    dry_run: bool = True,
    config: dict | None = None,
) -> dict:
    jobs = list_registered_jobs().get("jobs", [])
    results: list[dict] = []
    for job in jobs:
        due = should_run_job(job, now=now)
        if due.get("should_run"):
            results.append(run_registered_job(job["job_name"], db_path=db_path, dry_run=dry_run, config=config))
    return {
        "ok": not any(result.get("status") == "failed" for result in results),
        "ran_count": len(results),
        "results": results,
        "warnings": [warning for result in results for warning in result.get("warnings", [])],
        "errors": [error for result in results for error in result.get("errors", [])],
    }
