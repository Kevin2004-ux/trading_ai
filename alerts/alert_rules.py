from __future__ import annotations

from typing import Any


def _as_list(value: Any) -> list:
    return value if isinstance(value, list) else []


def _alert(severity: str, alert_type: str, title: str, message: str, payload: dict | None = None, source: str | None = None) -> dict:
    return {
        "severity": severity,
        "alert_type": alert_type,
        "title": title,
        "message": message,
        "payload": payload or {},
        "source": source,
    }


def _nested(payload: dict, *keys: str) -> Any:
    current: Any = payload
    for key in keys:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current


def _performance_context(job: dict, trading: dict) -> dict:
    candidates = [
        _nested(job, "result", "sections"),
        _nested(job, "result", "data"),
        job.get("result") if isinstance(job.get("result"), dict) else None,
        trading,
    ]
    context: dict[str, Any] = {}
    for candidate in candidates:
        if not isinstance(candidate, dict):
            continue
        for key in ("performance_attribution", "setup_diagnostics", "filter_attribution", "trade_error_analysis"):
            if isinstance(candidate.get(key), dict):
                context[key] = candidate[key]
    result = job.get("result") if isinstance(job.get("result"), dict) else {}
    for section in result.get("sections", []) if isinstance(result.get("sections"), list) else []:
        if not isinstance(section, dict):
            continue
        title = str(section.get("title") or "").lower()
        data = section.get("data") if isinstance(section.get("data"), dict) else {}
        if "performance attribution" in title:
            context["performance_attribution"] = data
        elif "setup diagnostics" in title:
            context["setup_diagnostics"] = data
        elif "filter attribution" in title:
            context["filter_attribution"] = data
        elif "trade error" in title:
            context["trade_error_analysis"] = data
    return context


def _stress_context(job: dict, trading: dict) -> dict:
    candidates = [
        job.get("result") if isinstance(job.get("result"), dict) else None,
        _nested(job, "result", "stress_test_summary"),
        trading.get("stress_test_summary") if isinstance(trading, dict) else None,
        _nested(trading, "summary", "stress_test_summary") if isinstance(trading, dict) else None,
    ]
    for candidate in candidates:
        if isinstance(candidate, dict) and (
            candidate.get("mode") == "stress_test"
            or candidate.get("scenario_count") is not None
            or candidate.get("estimated_total_loss_r") is not None
        ):
            return candidate
    return {}


def evaluate_alert_rules(
    job_result: dict | None = None,
    trading_result: dict | None = None,
    health_result: dict | None = None,
    config: dict | None = None,
) -> dict:
    alerts: list[dict] = []
    warnings: list[str] = []
    errors: list[str] = []

    job = job_result if isinstance(job_result, dict) else {}
    trading = trading_result if isinstance(trading_result, dict) else {}
    health = health_result if isinstance(health_result, dict) else {}

    if job:
        job_type = str(job.get("job_type") or job.get("job") or "")
        status = str(job.get("status") or "").lower()
        if status == "failed" or job.get("ok") is False:
            severity = "critical" if job_type in {"paper_cycle", "weekly_paper_cycle"} else "warning"
            alerts.append(_alert(severity, "job_failed", f"Scheduled job failed: {job.get('job_name')}", "A scheduled job failed.", job, source="job_runner"))

    performance = _performance_context(job, trading)
    stress = _stress_context(job, trading)
    if stress:
        failed_count = stress.get("failed_count") or 0
        if failed_count:
            alerts.append(_alert("critical", "stress_test_failed_expected_behavior", "Stress test failed expected behavior", "One or more simulated stress scenarios did not produce the expected safe behavior.", stress, source="stress_test"))
        estimated_loss = stress.get("estimated_total_loss_r")
        if estimated_loss is None and isinstance(stress.get("portfolio_stress"), dict):
            estimated_loss = stress["portfolio_stress"].get("estimated_total_loss_r")
        try:
            estimated_loss_value = abs(float(estimated_loss)) if estimated_loss is not None else None
        except (TypeError, ValueError):
            estimated_loss_value = None
        max_loss = (config or {}).get("STRESS_MAX_ACCEPTABLE_LOSS_R", 3.0)
        try:
            max_loss_value = float(max_loss)
        except (TypeError, ValueError):
            max_loss_value = 3.0
        if estimated_loss_value is not None and estimated_loss_value > max_loss_value:
            alerts.append(_alert("warning", "portfolio_stress_loss_high", "Portfolio stress loss is high", "Simulated paper portfolio stress loss exceeds the configured threshold.", stress, source="portfolio_stress"))
        for result in _as_list(stress.get("results")):
            if not isinstance(result, dict):
                continue
            scenario_name = str(result.get("scenario_name") or "")
            decision = _nested(result, "stress_result", "decision") or {}
            if scenario_name == "provider_outage" and decision.get("new_trades_allowed") is not False:
                alerts.append(_alert("critical", "provider_outage_not_handled_safely", "Provider outage was not handled safely", "Provider outage simulation did not block new simulated trades.", result, source="stress_test"))
            if scenario_name in {"audit_chain_failure_simulated", "schema_validation_failure_simulated"} and result.get("passed_expected_behavior") is False:
                alerts.append(_alert("critical", "simulated_control_failure_not_detected", "Simulated control failure was not detected", "A simulated audit/schema failure was not surfaced as expected.", result, source="stress_test"))
    attribution = performance.get("performance_attribution") if isinstance(performance.get("performance_attribution"), dict) else {}
    if attribution:
        closed_count = attribution.get("closed_trade_count") or 0
        expectancy = attribution.get("expectancy_r")
        try:
            expectancy_value = float(expectancy)
        except (TypeError, ValueError):
            expectancy_value = None
        if closed_count >= 8 and expectancy_value is not None and expectancy_value < 0:
            alerts.append(_alert("warning", "negative_expectancy", "Negative paper-trade expectancy", "Closed paper trades show negative expectancy over a usable sample.", attribution, source="performance_attribution"))
    setup_diag = performance.get("setup_diagnostics") if isinstance(performance.get("setup_diagnostics"), dict) else {}
    for setup in _as_list(setup_diag.get("setups")):
        if isinstance(setup, dict) and setup.get("status") == "disabled_candidate":
            alerts.append(_alert("warning", "setup_disabled_candidate", "Setup is a disabled candidate", "A setup is diagnosed as a disabled candidate. Do not disable automatically without setup-decay approval.", setup, source="strategy_diagnostics"))
    filter_attr = performance.get("filter_attribution") if isinstance(performance.get("filter_attribution"), dict) else {}
    for filter_row in _as_list(filter_attr.get("filters")):
        if not isinstance(filter_row, dict):
            continue
        name = filter_row.get("filter_name")
        applied = filter_row.get("applied_count") or 0
        blocked_or_downgraded = (filter_row.get("blocked_count") or 0) + (filter_row.get("downgraded_count") or 0)
        if name == "data_quality" and applied >= 5 and blocked_or_downgraded >= 3:
            alerts.append(_alert("warning", "repeated_data_quality_failures", "Repeated data-quality failures", "Data-quality filters repeatedly blocked or downgraded paper candidates.", filter_row, source="filter_attribution"))
        if name == "slippage_fill_quality" and applied >= 5 and blocked_or_downgraded >= 3:
            alerts.append(_alert("warning", "repeated_slippage_fill_issues", "Repeated slippage/fill issues", "Slippage or fill-quality filters repeatedly blocked or downgraded paper candidates.", filter_row, source="filter_attribution"))

    if trading:
        if trading.get("ok") is False:
            alerts.append(_alert("critical", "paper_cycle_failed", "Paper cycle failed", "Paper trading cycle returned ok=false.", trading, source="paper_cycle"))
        selected_count = _nested(trading, "summary", "selected_count")
        if selected_count == 0 or _nested(trading, "selection_result", "selection_summary", "selected_count") == 0:
            alerts.append(_alert("info", "no_trade_selected", "No paper trades selected", "No final paper trades were selected.", trading, source="paper_cycle"))
        data_quality = _nested(trading, "summary", "data_quality") or _nested(trading, "scan_result", "data_quality_summary") or {}
        if isinstance(data_quality, dict) and str(data_quality.get("worst_quality_label", "")).lower() in {"poor", "unavailable", "stale"}:
            alerts.append(_alert("warning", "data_quality_degraded", "Data quality degraded", "Scanner data quality was degraded.", data_quality, source="paper_cycle"))
        if _nested(trading, "summary", "circuit_breaker", "new_trades_allowed") is False:
            alerts.append(_alert("warning", "circuit_breaker_blocked", "Circuit breaker blocked trades", "Drawdown circuit breaker blocked new paper trades.", trading, source="paper_cycle"))
        if _nested(trading, "summary", "macro_risk", "new_trades_allowed") is False:
            alerts.append(_alert("warning", "macro_critical_block", "Macro risk blocked trades", "Critical macro risk blocked new paper trades.", trading, source="paper_cycle"))
        concentration_summary = trading.get("concentration_summary") or _nested(trading, "summary", "concentration_summary") or _nested(trading, "selection_result", "concentration_summary") or {}
        if isinstance(concentration_summary, dict) and concentration_summary.get("blocked_count", 0):
            alerts.append(_alert("warning", "concentration_block", "Concentration risk blocked candidates", "Concentration or correlation risk blocked one or more paper candidates.", concentration_summary, source="paper_cycle"))
        option_summary = _nested(trading, "summary", "option_risk_summary") or trading.get("option_risk_summary") or {}
        if isinstance(option_summary, dict) and option_summary.get("blocked_count", 0):
            alerts.append(_alert("info", "options_data_unavailable", "Options blocked or unavailable", "Options remain blocked/research-only.", option_summary, source="paper_cycle"))
        memory_summary = _nested(trading, "summary", "memory_summary") or trading.get("memory_summary") or {}
        if isinstance(memory_summary, dict) and memory_summary.get("ignored_count", 0):
            alerts.append(_alert("warning", "memory_quality_failed", "Memory quality failed", "One or more memory retrievals were ignored due to quality gates.", memory_summary, source="paper_cycle"))
        research_summary = trading.get("research_risk_summary") or _nested(trading, "summary", "research_risk_summary") or {}
        if isinstance(research_summary, dict) and research_summary.get("blocking_count", 0):
            severity = "critical" if (config or {}).get("CRITICAL_RESEARCH_ALERTS") else "warning"
            alerts.append(_alert(severity, "critical_news_or_filing_risk", "Critical research risk found", "Critical news or filing risk blocked/reduced a candidate.", research_summary, source="paper_cycle"))

    if health:
        startup = health.get("startup_readiness") if isinstance(health.get("startup_readiness"), dict) else health
        if isinstance(startup, dict) and startup.get("ok") is False:
            alerts.append(_alert("critical", "startup_not_ready", "Startup readiness failed", "Startup/runtime readiness is not ready.", startup, source="healthcheck"))
        audit = health.get("audit_chain") or health.get("audit_status") or {}
        if isinstance(audit, dict) and audit.get("ok") is False:
            alerts.append(_alert("critical", "audit_chain_failed", "Audit chain failed", "Audit chain verification failed.", audit, source="healthcheck"))
        schema = health.get("schema_validation") or health.get("validation") or {}
        if isinstance(schema, dict) and schema.get("ok") is False:
            alerts.append(_alert("critical", "schema_validation_failed", "Schema validation failed", "SQLite schema validation failed.", schema, source="healthcheck"))
        health_checks = health.get("checks") if isinstance(health.get("checks"), dict) else {}
        for name, check in health_checks.items():
            if isinstance(check, dict) and check.get("status") in {"unavailable", "failed"}:
                alerts.append(_alert("warning", "provider_unavailable", f"Provider unavailable: {name}", str(check.get("error") or "Provider unavailable."), check, source="live_dry_run"))

    return {"ok": True, "alerts": alerts, "count": len(alerts), "warnings": warnings, "errors": errors}
