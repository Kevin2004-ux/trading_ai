from __future__ import annotations

import os
from pathlib import Path
from typing import Any


DEFAULT_DB_PATH = "strategy_library.db"


def _value(overrides: dict | None, name: str, default: Any = None) -> Any:
    if isinstance(overrides, dict) and name in overrides:
        return overrides[name]
    return os.getenv(name, default)


def _bool_value(value: Any, default: bool = False) -> bool:
    if value is None:
        return default
    return str(value).strip().lower() in {"1", "true", "yes", "y", "on"}


def _float_value(value: Any) -> float | None:
    try:
        if value is None or str(value).strip() == "":
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _int_value(value: Any) -> int | None:
    try:
        if value is None or str(value).strip() == "":
            return None
        return int(value)
    except (TypeError, ValueError):
        return None


def _add_check(
    checks: list[dict],
    *,
    name: str,
    status: str,
    message: str,
    blocking: bool = False,
) -> None:
    checks.append(
        {
            "name": name,
            "status": status,
            "message": message,
            "blocking": bool(blocking),
        }
    )


def _database_check(db_path: str) -> tuple[str, str, bool]:
    path = Path(db_path).expanduser()
    parent = path.parent if str(path.parent) else Path(".")
    if not parent.exists():
        return "fail", f"Database parent directory does not exist: {parent}", True
    if path.exists():
        if not os.access(path, os.R_OK | os.W_OK):
            return "fail", f"Database path is not readable and writable: {path}", True
        return "pass", f"Database path is accessible: {path}", False
    if not os.access(parent, os.W_OK):
        return "fail", f"Database parent directory is not writable: {parent}", True
    return "pass", f"Database can be created at: {path}", False


def validate_startup_config(config: dict | None = None) -> dict:
    checks: list[dict] = []

    request_overrides_include_options = isinstance(config, dict) and "INCLUDE_OPTIONS" in config
    include_options_requested = _bool_value(_value(config, "INCLUDE_OPTIONS", "false"))
    stock_only = _bool_value(_value(config, "STOCK_ONLY", "false")) or (
        request_overrides_include_options and not include_options_requested
    )
    prefer_options = _bool_value(_value(config, "PREFER_OPTIONS", "false"))
    options_required = _bool_value(_value(config, "OPTIONS_REQUIRED", "false"))
    stock_fallback_allowed = _bool_value(_value(config, "STOCK_FALLBACK_ALLOWED", "true"), default=True)
    mode = str(_value(config, "MARKET_DATA_MODE", "auto") or "auto").lower()
    market_provider = str(_value(config, "MARKET_DATA_PROVIDER", "polygon") or "polygon").lower()
    options_provider = str(_value(config, "OPTIONS_DATA_PROVIDER", "disabled") or "disabled").lower()
    db_path = str(_value(config, "DATABASE_PATH", DEFAULT_DB_PATH) or DEFAULT_DB_PATH)
    live_quote_required = _bool_value(_value(config, "ALLOW_LIVE_QUOTE_REQUIRED", "false"))
    historical_fallback = _bool_value(_value(config, "ALLOW_HISTORICAL_BAR_FALLBACK", "true"), default=True)
    allow_options_without_quotes = _bool_value(_value(config, "ALLOW_OPTIONS_WITHOUT_QUOTES", "false"))
    options_globally_enabled = _bool_value(_value(config, "ENABLE_OPTIONS", "false"))
    options_enabled = False if stock_only else (include_options_requested or (options_globally_enabled and not request_overrides_include_options))
    options_only = _bool_value(_value(config, "OPTIONS_ONLY", "false")) or options_required
    gemini_enabled = _bool_value(_value(config, "ENABLE_GEMINI", "false"))
    memory_enabled = (
        _bool_value(_value(config, "MEMORY_ENABLED", "false"))
        or _bool_value(_value(config, "PINECONE_MEMORY_ENABLED", "false"))
        or _bool_value(_value(config, "ENABLE_PINECONE_MEMORY", "false"))
    )
    memory_required = _bool_value(_value(config, "MEMORY_REQUIRED", "false"))
    local_memory_fallback = _bool_value(_value(config, "LOCAL_MEMORY_FALLBACK", "true"), default=True)
    sec_research_enabled = _bool_value(_value(config, "SEC_RESEARCH_ENABLED", _value(config, "ENABLE_SEC_RESEARCH", "false")))
    sec_research_required = _bool_value(_value(config, "SEC_RESEARCH_REQUIRED", "false"))
    news_research_enabled = _bool_value(_value(config, "NEWS_RESEARCH_ENABLED", "false"))
    news_research_required = _bool_value(_value(config, "NEWS_RESEARCH_REQUIRED", "false"))
    short_interest_enabled = _bool_value(_value(config, "SHORT_INTEREST_ENABLED", "true"), default=True)
    short_interest_required = _bool_value(_value(config, "SHORT_INTEREST_REQUIRED", "false"))
    ibkr_news_diagnostic_enabled = _bool_value(_value(config, "IBKR_NEWS_DIAGNOSTIC_ENABLED", "false"))
    option_quotes_validated = _bool_value(_value(config, "OPTION_QUOTES_VALIDATED", "false"))
    scheduler_enabled = _bool_value(_value(config, "SCHEDULER_ENABLED", "false"))
    scheduler_timezone = str(_value(config, "SCHEDULER_TIMEZONE", "America/New_York") or "America/New_York")
    alerts_enabled = _bool_value(_value(config, "ALERTS_ENABLED", "true"), default=True)
    alert_channels = str(_value(config, "ALERT_CHANNELS", "local") or "local")
    alert_webhook_url = _value(config, "ALERT_WEBHOOK_URL", "")
    alert_email_enabled = _bool_value(_value(config, "ALERT_EMAIL_ENABLED", "false"))
    stress_testing_enabled = _bool_value(_value(config, "STRESS_TESTING_ENABLED", "true"), default=True)
    stress_test_job_enabled = _bool_value(_value(config, "STRESS_TEST_JOB_ENABLED", "false"))
    stress_max_loss_r = _float_value(_value(config, "STRESS_MAX_ACCEPTABLE_LOSS_R", "3.0"))
    stress_block_extreme_data_failure = _bool_value(_value(config, "STRESS_BLOCK_ON_EXTREME_DATA_FAILURE", "true"), default=True)

    _add_check(checks, name="market_data_provider", status="pass", message=f"Market data provider: {market_provider}")
    _add_check(checks, name="options_data_provider", status="pass", message=f"Options data provider: {options_provider}")
    _add_check(checks, name="market_data_mode", status="pass", message=f"Market data mode: {mode}")
    _add_check(
        checks,
        name="request_instrument_scope",
        status="pass",
        message=(
            "Stock-only request; options are ignored for startup blocking."
            if stock_only
            else "Options requested for this run." if options_enabled
            else "Stock-capable request; options are disabled or research-only."
        ),
    )

    db_status, db_message, db_blocking = _database_check(db_path)
    _add_check(checks, name="database_path", status=db_status, message=db_message, blocking=db_blocking)

    scan_max_concurrency = _int_value(_value(config, "SCAN_MAX_CONCURRENCY", "5"))
    if scan_max_concurrency is None or scan_max_concurrency < 1:
        _add_check(checks, name="scan_max_concurrency", status="fail", message="SCAN_MAX_CONCURRENCY must be an integer >= 1.", blocking=True)
    else:
        _add_check(checks, name="scan_max_concurrency", status="pass", message=f"SCAN_MAX_CONCURRENCY={scan_max_concurrency}")

    for env_name, default in (
        ("SCAN_TICKER_TIMEOUT_SECONDS", "15"),
        ("SCAN_TOTAL_TIMEOUT_SECONDS", "180"),
        ("IBKR_TIMEOUT_SECONDS", "10"),
    ):
        value = _float_value(_value(config, env_name, default))
        if value is None or value <= 0:
            _add_check(checks, name=env_name.lower(), status="fail", message=f"{env_name} must be a positive number.", blocking=True)
        else:
            _add_check(checks, name=env_name.lower(), status="pass", message=f"{env_name}={value}")

    ibkr_max_concurrent = _int_value(_value(config, "IBKR_MAX_CONCURRENT_REQUESTS", "3"))
    ibkr_rps = _float_value(_value(config, "IBKR_REQUESTS_PER_SECOND", "2"))
    if ibkr_max_concurrent is None or ibkr_max_concurrent < 1:
        _add_check(checks, name="ibkr_max_concurrent_requests", status="fail", message="IBKR_MAX_CONCURRENT_REQUESTS must be >= 1.", blocking=True)
    else:
        _add_check(checks, name="ibkr_max_concurrent_requests", status="pass", message=f"IBKR_MAX_CONCURRENT_REQUESTS={ibkr_max_concurrent}")
    if ibkr_rps is None or ibkr_rps <= 0:
        _add_check(checks, name="ibkr_requests_per_second", status="fail", message="IBKR_REQUESTS_PER_SECOND must be > 0.", blocking=True)
    else:
        _add_check(checks, name="ibkr_requests_per_second", status="pass", message=f"IBKR_REQUESTS_PER_SECOND={ibkr_rps}")

    if market_provider == "ibkr" or options_provider == "ibkr":
        read_only = _bool_value(_value(config, "IBKR_READ_ONLY", None))
        if not read_only:
            _add_check(checks, name="ibkr_read_only", status="fail", message="IBKR_READ_ONLY must be true when IBKR is configured.", blocking=True)
        else:
            _add_check(checks, name="ibkr_read_only", status="pass", message="IBKR read-only mode is enabled.")

        for env_name, default in (("IBKR_HOST", "127.0.0.1"), ("IBKR_PORT", "7496"), ("IBKR_CLIENT_ID", "123")):
            value = _value(config, env_name, default)
            if value is None or str(value).strip() == "":
                _add_check(checks, name=env_name.lower(), status="fail", message=f"{env_name} is required for IBKR.", blocking=True)
            else:
                _add_check(checks, name=env_name.lower(), status="pass", message=f"{env_name} is configured.")

        _add_check(checks, name="ibkr_connectivity", status="warn", message="IBKR provider is configured, but TWS connectivity has not been checked yet.")

    if market_provider == "polygon" and live_quote_required and not _value(config, "POLYGON_API_KEY"):
        _add_check(checks, name="polygon_api_key", status="fail", message="POLYGON_API_KEY is required when live quotes are required.", blocking=True)
    elif market_provider == "polygon" and not _value(config, "POLYGON_API_KEY"):
        _add_check(checks, name="polygon_api_key", status="warn", message="POLYGON_API_KEY is missing; live Polygon market data is unavailable.")

    if historical_fallback:
        _add_check(checks, name="historical_bar_fallback", status="warn", message="Historical bar fallback is enabled; scans may use latest daily close when quote data is unavailable.")
    else:
        _add_check(checks, name="historical_bar_fallback", status="pass", message="Historical bar fallback is disabled.")

    if not live_quote_required:
        _add_check(checks, name="live_quote_required", status="warn", message="Live quote is not required; after-close swing scans may proceed with fallback data.")
    else:
        _add_check(checks, name="live_quote_required", status="pass", message="Live quotes are required by configuration.")

    if allow_options_without_quotes:
        _add_check(checks, name="allow_options_without_quotes", status="fail", message="ALLOW_OPTIONS_WITHOUT_QUOTES=true is unsafe; option recommendations require usable quotes/fills.", blocking=True)
    elif options_enabled and not option_quotes_validated:
        option_quotes_blocking = options_only or (prefer_options and not stock_fallback_allowed)
        _add_check(
            checks,
            name="options_quotes",
            status="fail" if option_quotes_blocking else "warn",
            message="Options provider is enabled but option quotes have not been validated; final option recommendations remain blocked.",
            blocking=option_quotes_blocking,
        )
    elif options_enabled:
        _add_check(checks, name="options_quotes", status="pass", message="Options are enabled and quote validation is marked true.")
    else:
        _add_check(checks, name="options_quotes", status="warn", message="Options are disabled or research-only; final option recommendations remain blocked.")

    try:
        from zoneinfo import ZoneInfo

        ZoneInfo(scheduler_timezone)
        _add_check(checks, name="scheduler_timezone", status="pass", message=f"Scheduler timezone is valid: {scheduler_timezone}")
    except Exception:
        _add_check(checks, name="scheduler_timezone", status="fail", message=f"SCHEDULER_TIMEZONE is invalid: {scheduler_timezone}", blocking=True)
    if scheduler_enabled:
        _add_check(checks, name="scheduler_enabled", status="pass", message="Scheduler is enabled for explicit job execution.")
    else:
        _add_check(checks, name="scheduler_enabled", status="warn", message="Scheduler is disabled; paper cycles can still be run manually.")
    if alerts_enabled:
        _add_check(checks, name="alerts_enabled", status="pass", message=f"Alerts are enabled for channels: {alert_channels}.")
    else:
        _add_check(checks, name="alerts_enabled", status="warn", message="Alerts are disabled.")
    if "webhook" in {item.strip().lower() for item in alert_channels.split(",")} and not alert_webhook_url:
        _add_check(checks, name="alert_webhook_url", status="warn", message="Webhook alert channel is configured but ALERT_WEBHOOK_URL is missing; external sends remain disabled.")
    if alert_email_enabled:
        _add_check(checks, name="alert_email", status="warn", message="Email alerts are enabled but no project email sender is configured; tests should mock sending.")
    else:
        _add_check(checks, name="alert_email", status="warn", message="Email alerts are disabled.")

    if stress_testing_enabled:
        _add_check(checks, name="stress_testing_enabled", status="pass", message="Stress testing is enabled for simulated paper-trading diagnostics.")
    else:
        _add_check(checks, name="stress_testing_enabled", status="warn", message="Stress testing is disabled; paper cycles can still run manually.")
    if stress_test_job_enabled:
        _add_check(checks, name="stress_test_job_enabled", status="pass", message="Stress-test scheduled job is explicitly enabled.")
    else:
        _add_check(checks, name="stress_test_job_enabled", status="warn", message="Stress-test scheduled job is disabled by default; run stress tests manually or enable intentionally.")
    if stress_max_loss_r is None or stress_max_loss_r <= 0:
        _add_check(checks, name="stress_max_acceptable_loss_r", status="fail", message="STRESS_MAX_ACCEPTABLE_LOSS_R must be a positive number.", blocking=True)
    else:
        _add_check(checks, name="stress_max_acceptable_loss_r", status="pass", message=f"STRESS_MAX_ACCEPTABLE_LOSS_R={stress_max_loss_r}")
    if stress_block_extreme_data_failure:
        _add_check(checks, name="stress_block_on_extreme_data_failure", status="pass", message="Extreme simulated data failures block final recommendations under stress tests.")
    else:
        _add_check(checks, name="stress_block_on_extreme_data_failure", status="warn", message="Extreme simulated data failures are not configured to block; this is unsafe for final recommendations.")

    if gemini_enabled and not _value(config, "GEMINI_API_KEY"):
        _add_check(checks, name="gemini_api_key", status="fail", message="GEMINI_API_KEY is required when Gemini features are enabled.", blocking=True)
    elif not _value(config, "GEMINI_API_KEY"):
        _add_check(checks, name="gemini_api_key", status="warn", message="GEMINI_API_KEY is missing; AI narration is unavailable but optional.")

    pinecone_namespace = _value(config, "PINECONE_NAMESPACE", "trading_ai")
    if memory_enabled:
        if not _value(config, "PINECONE_API_KEY") or not _value(config, "PINECONE_INDEX_NAME"):
            if memory_required:
                _add_check(checks, name="pinecone_memory", status="fail", message="Memory is required but PINECONE_API_KEY or PINECONE_INDEX_NAME is missing.", blocking=True)
            else:
                _add_check(checks, name="pinecone_memory", status="warn", message="Memory is enabled but Pinecone is missing; local/SQLite fallback or explanation-only memory should be used.")
        else:
            _add_check(checks, name="pinecone_memory", status="pass", message=f"Pinecone memory configuration is present for namespace {pinecone_namespace}.")
        if local_memory_fallback:
            _add_check(checks, name="local_memory_fallback", status="pass", message="Local SQLite memory fallback is enabled.")
        else:
            _add_check(checks, name="local_memory_fallback", status="warn", message="Local SQLite memory fallback is disabled.")
    else:
        _add_check(checks, name="pinecone_memory", status="warn", message="Memory is disabled or Pinecone memory is optional and not fully configured.")

    if sec_research_required and not sec_research_enabled:
        _add_check(checks, name="sec_research_required", status="fail", message="SEC_RESEARCH_REQUIRED=true but SEC research is disabled.", blocking=True)
    elif sec_research_enabled and not _value(config, "SEC_USER_AGENT"):
        _add_check(
            checks,
            name="sec_user_agent",
            status="fail",
            message="SEC_USER_AGENT is required when SEC research is enabled.",
            blocking=sec_research_required,
        )
    elif not _value(config, "SEC_USER_AGENT"):
        _add_check(checks, name="sec_user_agent", status="warn", message="SEC_USER_AGENT is missing; SEC research should stay disabled.")

    if news_research_required and not news_research_enabled:
        _add_check(checks, name="news_research_required", status="fail", message="NEWS_RESEARCH_REQUIRED=true but NEWS_RESEARCH_ENABLED=false.", blocking=True)
    elif news_research_enabled and not ibkr_news_diagnostic_enabled:
        _add_check(checks, name="news_provider", status="warn", message="News research is enabled, but IBKR_NEWS_DIAGNOSTIC_ENABLED is false; provider checks remain unavailable.")
    elif news_research_enabled:
        _add_check(checks, name="news_provider", status="warn", message="News research is enabled; provider availability has not been checked.")
    else:
        _add_check(checks, name="news_provider", status="warn", message="News research is disabled and optional.")

    if short_interest_required and not short_interest_enabled:
        _add_check(checks, name="short_interest_required", status="fail", message="SHORT_INTEREST_REQUIRED=true but SHORT_INTEREST_ENABLED=false.", blocking=True)
    elif short_interest_enabled:
        _add_check(checks, name="short_interest_provider", status="warn", message="Short-interest research is enabled; missing provider data will warn but not block unless required.")
    else:
        _add_check(checks, name="short_interest_provider", status="warn", message="Short-interest research is disabled and optional.")

    warnings = [check["message"] for check in checks if check["status"] == "warn"]
    errors = [check["message"] for check in checks if check["status"] == "fail"]
    blocking_errors = [check for check in checks if check["status"] == "fail" and check["blocking"]]
    readiness = "not_ready" if blocking_errors else "ready_with_warnings" if warnings else "ready"

    return {
        "ok": not blocking_errors,
        "readiness": readiness,
        "mode": mode,
        "checks": checks,
        "warnings": warnings,
        "errors": errors,
        "safe_to_run_paper_cycle": not blocking_errors,
        "safe_to_run_options": options_enabled and option_quotes_validated and not allow_options_without_quotes and not blocking_errors,
        "safe_to_use_live_provider": not blocking_errors and (market_provider != "polygon" or bool(_value(config, "POLYGON_API_KEY")) or not live_quote_required),
        "safe_to_run_sec_research": sec_research_enabled and bool(_value(config, "SEC_USER_AGENT")),
        "safe_to_run_news_research": news_research_enabled and (ibkr_news_diagnostic_enabled or not news_research_required),
        "safe_to_run_short_interest_research": short_interest_enabled,
        "safe_to_use_memory": memory_enabled and (bool(_value(config, "PINECONE_API_KEY") and _value(config, "PINECONE_INDEX_NAME")) or local_memory_fallback),
        "safe_to_use_scheduler": True,
        "safe_to_use_alerts": alerts_enabled,
        "safe_to_use_stress_testing": stress_testing_enabled and stress_max_loss_r is not None and stress_max_loss_r > 0 and not blocking_errors,
    }
