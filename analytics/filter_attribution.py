from __future__ import annotations

from collections import defaultdict
from typing import Any

from analytics.performance_attribution import calculate_r_multiple


FILTER_KEYWORDS = {
    "data_quality": ("data_quality", "freshness", "stale", "fallback"),
    "market_regime": ("market_regime", "regime"),
    "macro_risk": ("macro", "fomc", "cpi", "jobs"),
    "circuit_breaker": ("circuit_breaker", "drawdown", "loss_streak"),
    "concentration": ("concentration", "correlation", "sector_exposure"),
    "volume_profile": ("volume_profile", "poc", "value_area"),
    "timeframe_confirmation": ("timeframe", "weekly_trend", "daily_trend"),
    "filing_news_risk": ("filing", "news", "headline", "sec"),
    "short_interest_borrow_pressure": ("short_interest", "borrow", "squeeze"),
    "memory_feedback": ("memory", "annotation", "feedback"),
    "options_gating": ("option", "options", "greeks", "iv"),
    "slippage_fill_quality": ("slippage", "fill_quality", "paper_fill"),
}


def _as_dict(value: Any) -> dict:
    return value if isinstance(value, dict) else {}


def _flatten(value: Any) -> str:
    if isinstance(value, dict):
        return " ".join(f"{key} {_flatten(item)}" for key, item in value.items())
    if isinstance(value, list):
        return " ".join(_flatten(item) for item in value)
    return str(value or "")


def _status_for_filter(candidate: dict, filter_name: str) -> str | None:
    text = _flatten(candidate).lower()
    keywords = FILTER_KEYWORDS[filter_name]
    if not any(keyword in text for keyword in keywords):
        return None
    passed = candidate.get("passed_constraints")
    recommendation_status = str(candidate.get("recommendation_status") or _as_dict(candidate.get("constraint_results_json")).get("recommendation_status") or "").lower()
    rejection_reason = str(candidate.get("rejection_reason") or "").lower()
    failed_text = _flatten(candidate.get("failed_constraints_json")).lower()
    if passed is False or passed == 0 or recommendation_status in {"rejected", "blocked", "failed"} or any(keyword in rejection_reason or keyword in failed_text for keyword in keywords):
        return "blocked"
    if any(word in text for word in ("warning", "downgrade", "reduced", "watchlist", "poor", "usable_with_warnings")):
        return "downgraded"
    return "allowed"


def _avg(values: list[float]) -> float | None:
    return round(sum(values) / len(values), 4) if values else None


def _trade_lookup(trades: list[dict] | None) -> dict[tuple[str, str], list[float]]:
    lookup: dict[tuple[str, str], list[float]] = defaultdict(list)
    for trade in trades or []:
        if not isinstance(trade, dict):
            continue
        value = calculate_r_multiple(trade)
        if value is None:
            continue
        ticker = str(trade.get("ticker") or "").upper()
        setup = str(trade.get("setup_type") or trade.get("strategy") or "")
        lookup[(ticker, setup)].append(value)
        lookup[(ticker, "")].append(value)
    return lookup


def analyze_filter_attribution(
    candidates: list[dict],
    trades: list[dict] | None = None,
    config: dict | None = None,
) -> dict:
    trade_r = _trade_lookup(trades)
    min_sample = int((config or {}).get("min_filter_sample", 5))
    filters = []
    for filter_name in FILTER_KEYWORDS:
        statuses: list[str] = []
        pass_outcomes: list[float] = []
        warning_outcomes: list[float] = []
        for candidate in candidates or []:
            if not isinstance(candidate, dict):
                continue
            status = _status_for_filter(candidate, filter_name)
            if status is None:
                continue
            statuses.append(status)
            ticker = str(candidate.get("ticker") or "").upper()
            setup = str(candidate.get("setup_type") or candidate.get("strategy") or "")
            outcomes = trade_r.get((ticker, setup)) or trade_r.get((ticker, "")) or []
            if status == "allowed":
                pass_outcomes.extend(outcomes)
            elif status == "downgraded":
                warning_outcomes.extend(outcomes)

        applied_count = len(statuses)
        blocked_count = statuses.count("blocked")
        downgraded_count = statuses.count("downgraded")
        allowed_count = statuses.count("allowed")
        avg_pass = _avg(pass_outcomes)
        avg_warning = _avg(warning_outcomes)
        warnings: list[str] = []
        reasons: list[str] = []
        if applied_count < min_sample:
            diagnostic_status = "insufficient_data"
            warnings.append("Small sample; signal appears tentative and should not be treated as causal.")
        elif avg_pass is not None and avg_pass < 0 and allowed_count:
            diagnostic_status = "too_loose"
            reasons.append("Allowed candidates with this filter context have negative average R.")
        elif blocked_count > allowed_count * 2 and (avg_pass or 0) > 0:
            diagnostic_status = "too_strict"
            reasons.append("Filter blocks many candidates while passed outcomes appear positive; review strictness conservatively.")
        elif avg_pass is not None and avg_pass > 0 and blocked_count:
            diagnostic_status = "useful"
            reasons.append("Signal appears useful: passed candidates have positive average R while some candidates were blocked.")
        else:
            diagnostic_status = "neutral"
            reasons.append("No clear conservative attribution signal yet.")

        filters.append(
            {
                "filter_name": filter_name,
                "applied_count": applied_count,
                "blocked_count": blocked_count,
                "downgraded_count": downgraded_count,
                "allowed_count": allowed_count,
                "avg_outcome_r_after_pass": avg_pass,
                "avg_outcome_r_after_warning": avg_warning,
                "diagnostic_status": diagnostic_status,
                "reasons": reasons,
                "warnings": warnings,
            }
        )
    return {
        "ok": True,
        "filters": filters,
        "warnings": [warning for item in filters for warning in item.get("warnings", [])],
        "errors": [],
    }


def evaluate_filter_effectiveness(
    historical_decisions: list[dict],
    config: dict | None = None,
) -> dict:
    return analyze_filter_attribution(historical_decisions, trades=historical_decisions, config=config)
