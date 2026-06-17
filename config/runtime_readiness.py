from __future__ import annotations

import os
from typing import Any

from config.startup_validator import DEFAULT_DB_PATH, validate_startup_config
from db.schema_manager import get_schema_version, validate_schema


def _status(ok: bool, warning: bool = False) -> str:
    if ok and not warning:
        return "ready"
    if ok and warning:
        return "ready_with_warnings"
    return "not_ready"


def _category(name: str, ok: bool, message: str, warnings: list[str] | None = None, errors: list[str] | None = None) -> dict:
    warnings = warnings or []
    errors = errors or []
    return {
        "name": name,
        "ok": bool(ok),
        "status": _status(bool(ok), bool(warnings)),
        "message": message,
        "warnings": warnings,
        "errors": errors,
    }


def _bool_config(config: dict | None, name: str, default: str = "false") -> bool:
    value = config.get(name) if isinstance(config, dict) and name in config else os.getenv(name, default)
    return str(value).strip().lower() in {"1", "true", "yes", "y", "on"}


def check_runtime_readiness(config: dict | None = None, include_live_checks: bool = False) -> dict:
    startup = validate_startup_config(config=config)
    db_path = (config or {}).get("DATABASE_PATH") if isinstance(config, dict) else None
    db_path = db_path or DEFAULT_DB_PATH
    schema_validation = validate_schema(db_path, apply_migrations=False)
    schema_version = get_schema_version(db_path, apply_migrations=False) if schema_validation.get("ok") else {"ok": False, "current_version": None}

    categories: dict[str, dict] = {}
    categories["database_ready"] = _category(
        "database_ready",
        bool(schema_validation.get("ok")),
        "Database schema is present." if schema_validation.get("ok") else "Database schema is missing or not migrated.",
        warnings=[] if schema_validation.get("ok") else ["Run db-migrate before production use."],
        errors=schema_validation.get("errors", []),
    )
    categories["providers_configured"] = _category(
        "providers_configured",
        startup.get("safe_to_use_live_provider", False),
        "Provider configuration is safe enough for configured mode.",
        warnings=[warning for warning in startup.get("warnings", []) if "provider" in warning.lower() or "POLYGON" in warning or "quote" in warning],
    )
    categories["ibkr_safe_mode"] = _category(
        "ibkr_safe_mode",
        not any(check["name"] == "ibkr_read_only" and check["status"] == "fail" for check in startup.get("checks", [])),
        "IBKR read-only safety is valid or IBKR is not active.",
        errors=[error for error in startup.get("errors", []) if "IBKR_READ_ONLY" in error],
    )
    categories["options_ready"] = _category(
        "options_ready",
        startup.get("safe_to_run_options", False),
        "Options are ready for final recommendations." if startup.get("safe_to_run_options") else "Options are disabled, research-only, or blocked until quote validation passes.",
        warnings=[] if startup.get("safe_to_run_options") else ["Options final recommendations remain blocked."],
    )
    categories["ai_ready"] = _category(
        "ai_ready",
        not any(check["name"] == "gemini_api_key" and check["status"] == "fail" for check in startup.get("checks", [])),
        "AI narration is available or optional.",
        warnings=[warning for warning in startup.get("warnings", []) if "GEMINI" in warning],
    )
    categories["memory_ready"] = _category(
        "memory_ready",
        not any(check["name"] == "pinecone_memory" and check["status"] == "fail" for check in startup.get("checks", [])),
        "Semantic memory is available or optional.",
        warnings=[warning for warning in startup.get("warnings", []) if "Pinecone" in warning or "Memory" in warning or "memory" in warning],
    )
    sec_user_agent_failed = any(check["name"] == "sec_user_agent" and check["status"] == "fail" for check in startup.get("checks", []))
    sec_research_required = _bool_config(config, "SEC_RESEARCH_REQUIRED")
    news_research_required = _bool_config(config, "NEWS_RESEARCH_REQUIRED")
    short_interest_required = _bool_config(config, "SHORT_INTEREST_REQUIRED")
    categories["research_ready"] = _category(
        "research_ready",
        not sec_user_agent_failed
        and not any(check["name"] in {"news_research_required", "short_interest_required"} and check["status"] == "fail" for check in startup.get("checks", [])),
        "Research risk configuration is ready."
        if not sec_user_agent_failed
        else "SEC filing research is unavailable until SEC_USER_AGENT is configured.",
        warnings=[warning for warning in startup.get("warnings", []) if any(token in warning for token in ("SEC", "News", "Short-interest"))],
        errors=[
            error
            for error in startup.get("errors", [])
            if any(token in error for token in ("SEC_USER_AGENT", "NEWS_RESEARCH_REQUIRED", "SHORT_INTEREST_REQUIRED"))
        ],
    )
    categories["scan_runtime_ready"] = _category(
        "scan_runtime_ready",
        startup.get("safe_to_run_paper_cycle", False),
        "Scan runtime limits are valid." if startup.get("safe_to_run_paper_cycle") else "Scan runtime is blocked by startup validation.",
        warnings=startup.get("warnings", []),
        errors=startup.get("errors", []),
    )
    categories["scheduler_ready"] = _category(
        "scheduler_ready",
        not any(check["name"] == "scheduler_timezone" and check["status"] == "fail" for check in startup.get("checks", [])),
        "Scheduler configuration is valid.",
        warnings=[warning for warning in startup.get("warnings", []) if "Scheduler" in warning or "scheduler" in warning],
    )
    categories["alerts_ready"] = _category(
        "alerts_ready",
        True,
        "Local structured alerts are available.",
        warnings=[warning for warning in startup.get("warnings", []) if "alert" in warning.lower() or "Email" in warning or "Webhook" in warning],
    )
    categories["stress_testing_ready"] = _category(
        "stress_testing_ready",
        startup.get("safe_to_use_stress_testing", False),
        "Stress testing is ready for simulated paper-trading diagnostics."
        if startup.get("safe_to_use_stress_testing")
        else "Stress testing is disabled or misconfigured.",
        warnings=[warning for warning in startup.get("warnings", []) if "Stress" in warning or "stress" in warning],
        errors=[error for error in startup.get("errors", []) if "STRESS" in error or "stress" in error],
    )

    live_checks: dict[str, Any] | None = None
    if include_live_checks:
        from diagnostics.live_dry_run import run_provider_dry_run

        live_checks = run_provider_dry_run(
            include_market_data=True,
            include_news=False,
            include_sec_filings=False,
            include_earnings_transcripts=False,
            include_options=False,
            include_memory=False,
            db_path=db_path,
        )

    blocking_categories = [
        category
        for category in categories.values()
        if not category["ok"]
        and category["name"] != "options_ready"
        and category["name"] != "stress_testing_ready"
        and (category["name"] != "research_ready" or sec_research_required or news_research_required or short_interest_required)
    ]
    warnings = list(startup.get("warnings", []))
    if not schema_validation.get("ok"):
        warnings.append("Database schema is not fully migrated; run db-migrate.")
    if live_checks and live_checks.get("warnings"):
        warnings.extend(str(item) for item in live_checks.get("warnings", []))
    errors = list(startup.get("errors", []))
    if live_checks and live_checks.get("errors"):
        errors.extend(str(item) for item in live_checks.get("errors", []))

    ready = startup.get("ok", False) and not blocking_categories
    readiness = "not_ready" if not ready else "ready_with_warnings" if warnings else "ready"

    return {
        "ok": ready,
        "readiness": readiness,
        "startup_validation": startup,
        "schema_version": schema_version,
        "schema_validation": schema_validation,
        "categories": categories,
        "live_checks": live_checks,
        "warnings": warnings,
        "errors": errors,
    }
