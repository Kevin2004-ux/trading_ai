from __future__ import annotations

from copy import deepcopy
from typing import Any


BLOCKING_SCENARIOS = {
    "macro_critical_event",
    "bad_data_stale_prices",
    "provider_outage",
    "news_or_filing_shock",
    "circuit_breaker_loss_streak",
}
DATA_FAILURE_SCENARIOS = {"bad_data_stale_prices", "provider_outage"}


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None:
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _risk_multiplier(scenario: dict) -> float:
    risk_shocks = scenario.get("risk_shocks") if isinstance(scenario.get("risk_shocks"), dict) else {}
    severity = str(scenario.get("severity", "medium")).lower()
    default = {"low": 0.9, "medium": 0.75, "high": 0.5, "extreme": 0.0}.get(severity, 0.75)
    return max(0.0, min(1.0, _safe_float(risk_shocks.get("risk_multiplier"), default)))


def _estimated_drawdown(scenario: dict, item_count: int = 1) -> float:
    risk_shocks = scenario.get("risk_shocks") if isinstance(scenario.get("risk_shocks"), dict) else {}
    base = _safe_float(risk_shocks.get("drawdown_r"), -1.0)
    return round(base * max(item_count, 1), 4)


def _estimated_gap_loss(candidate: dict, scenario: dict) -> float:
    entry = _safe_float(candidate.get("entry_price"), 0.0)
    market_shocks = scenario.get("market_shocks") if isinstance(scenario.get("market_shocks"), dict) else {}
    gap_percent = _safe_float(market_shocks.get("gap_percent") or market_shocks.get("sector_gap_percent"), 0.0)
    direction = str(candidate.get("direction") or "long").lower()
    if direction == "short":
        gap_percent = -gap_percent
    return round(entry * gap_percent / 100.0, 4) if entry else 0.0


def _base_response(pre_stress: dict, post_stress: dict, scenario: dict, reasons: list[str], warnings: list[str]) -> dict:
    scenario_name = scenario.get("scenario_name", "unknown")
    should_block = scenario_name in BLOCKING_SCENARIOS or bool((scenario.get("expected_behavior") or {}).get("should_block_new_trades"))
    risk_multiplier = _risk_multiplier(scenario)
    return {
        "ok": True,
        "scenario_name": scenario_name,
        "severity": scenario.get("severity", "medium"),
        "pre_stress": pre_stress,
        "post_stress": post_stress,
        "risk_impact": {
            "risk_multiplier": risk_multiplier,
            "estimated_drawdown_r": _estimated_drawdown(scenario),
            "estimated_gap_loss": _estimated_gap_loss(pre_stress, scenario),
            "liquidity_impact": (scenario.get("risk_shocks") or {}).get("liquidity_impact", "normal"),
            "data_quality_impact": (scenario.get("risk_shocks") or {}).get("data_quality_impact", "normal"),
        },
        "decision": {
            "new_trades_allowed": not should_block,
            "recommendation_status": "blocked" if should_block else "downgraded" if risk_multiplier < 1.0 else "unchanged",
            "reasons": reasons,
        },
        "warnings": warnings,
        "errors": [],
    }


def apply_stress_scenario(
    base_result: dict,
    scenario: dict,
    config: dict | None = None,
) -> dict:
    pre = deepcopy(base_result) if isinstance(base_result, dict) else {}
    post = deepcopy(pre)
    scenario_name = scenario.get("scenario_name", "unknown")
    risk_multiplier = _risk_multiplier(scenario)
    reasons = [f"Applied simulated stress scenario: {scenario_name}."]
    warnings: list[str] = []
    if risk_multiplier < 1.0:
        post.setdefault("stress_adjustments", {})["risk_multiplier"] = risk_multiplier
        reasons.append(f"Stress scenario reduced simulated risk multiplier to {risk_multiplier}.")
    if scenario_name in DATA_FAILURE_SCENARIOS:
        post.setdefault("data_quality", {})["final_recommendation_allowed"] = False
        post["data_quality"]["quality_label"] = (scenario.get("data_shocks") or {}).get("quality_label", "unavailable")
        warnings.append("Extreme simulated data failure blocks new paper recommendations.")
    if scenario_name in {"partial_scan_timeout"}:
        post.setdefault("scan_execution_summary", {})["partial_results_used"] = True
        post["scan_execution_summary"]["warnings"] = ["Simulated partial scan timeout; partial results preserved."]
        warnings.append("Partial scan timeout simulated; output remains structured.")
    if scenario_name in {"audit_chain_failure_simulated", "schema_validation_failure_simulated"}:
        post.setdefault("diagnostics", {})[scenario_name] = False
        warnings.append("Simulated control-plane failure detected without mutating SQLite.")
    return _base_response(pre, post, scenario, reasons, warnings)


def run_stress_test_on_candidate(
    candidate: dict,
    scenario: dict,
    config: dict | None = None,
) -> dict:
    pre = deepcopy(candidate) if isinstance(candidate, dict) else {}
    result = apply_stress_scenario(pre, scenario, config=config)
    post = deepcopy(result["post_stress"])
    scenario_name = scenario.get("scenario_name", "unknown")
    original_status = str(pre.get("recommendation_status") or "").lower()
    original_passed = pre.get("passed", True)
    if original_status in {"rejected", "blocked"} or original_passed is False:
        post["recommendation_status"] = pre.get("recommendation_status", "rejected")
        post["passed"] = False
        result["decision"]["recommendation_status"] = "unchanged"
        result["decision"]["new_trades_allowed"] = False
        result["decision"]["reasons"].append("Stress tests never make a rejected candidate eligible.")
    elif scenario_name in BLOCKING_SCENARIOS:
        post["recommendation_status"] = "rejected"
        post["passed"] = False
        post["failed_constraints"] = list(post.get("failed_constraints", [])) + [f"stress_{scenario_name}"]
        post["rejection_reason"] = f"Blocked under stress scenario: {scenario_name}."
    elif _risk_multiplier(scenario) < 1.0:
        post["recommendation_status"] = "watchlist"
        post["stress_risk_multiplier"] = _risk_multiplier(scenario)

    if str(pre.get("asset_type", "")).lower() == "option" or pre.get("option_contract"):
        if original_status != "recommendable":
            post["recommendation_status"] = pre.get("recommendation_status", "research_only")
        result["decision"]["reasons"].append("Stress testing never unblocks option candidates.")
    result["post_stress"] = post
    result["risk_impact"]["estimated_gap_loss"] = _estimated_gap_loss(pre, scenario)
    return result


def run_stress_test_on_portfolio(
    open_trades: list[dict],
    scenario: dict,
    config: dict | None = None,
) -> dict:
    trades = [trade for trade in open_trades or [] if isinstance(trade, dict)]
    stressed = [run_stress_test_on_candidate(trade, scenario, config=config) for trade in trades]
    total_gap_loss = round(sum(_safe_float(item.get("risk_impact", {}).get("estimated_gap_loss")) for item in stressed), 4)
    total_drawdown = _estimated_drawdown(scenario, item_count=len(trades))
    reasons = [f"Stress-tested {len(trades)} open simulated trade(s)."]
    if total_drawdown <= -_safe_float((config or {}).get("max_acceptable_loss_r"), 3.0):
        reasons.append("Estimated stress drawdown exceeds configured threshold.")
    return {
        "ok": True,
        "scenario_name": scenario.get("scenario_name", "unknown"),
        "severity": scenario.get("severity", "medium"),
        "pre_stress": {"open_trade_count": len(trades), "open_trades": trades},
        "post_stress": {"stressed_trades": stressed},
        "risk_impact": {
            "risk_multiplier": _risk_multiplier(scenario),
            "estimated_drawdown_r": total_drawdown,
            "estimated_gap_loss": total_gap_loss,
            "liquidity_impact": (scenario.get("risk_shocks") or {}).get("liquidity_impact", "normal"),
            "data_quality_impact": (scenario.get("risk_shocks") or {}).get("data_quality_impact", "normal"),
        },
        "decision": {
            "new_trades_allowed": scenario.get("scenario_name") not in BLOCKING_SCENARIOS,
            "recommendation_status": "blocked" if scenario.get("scenario_name") in BLOCKING_SCENARIOS else "downgraded",
            "reasons": reasons,
        },
        "warnings": [reason for reason in reasons if "exceeds" in reason],
        "errors": [],
    }
