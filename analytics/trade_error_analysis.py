from __future__ import annotations

from collections import Counter
from typing import Any

from analytics.performance_attribution import calculate_r_multiple


FAILURE_CATEGORIES = [
    "bad_entry",
    "stop_too_tight",
    "target_too_aggressive",
    "poor_risk_reward",
    "market_regime_shift",
    "macro_event_risk",
    "earnings_or_filing_risk",
    "news_risk",
    "concentration_risk",
    "technical_confirmation_failed",
    "data_quality_issue",
    "slippage_or_fill_issue",
    "setup_decay",
    "unknown",
]


def _safe_float(value: Any) -> float | None:
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _flatten(value: Any) -> str:
    if isinstance(value, dict):
        return " ".join(f"{key} {_flatten(item)}" for key, item in value.items())
    if isinstance(value, list):
        return " ".join(_flatten(item) for item in value)
    return str(value or "")


def _context_text(trade: dict) -> str:
    parts = [
        trade.get("notes"),
        trade.get("thesis"),
        trade.get("invalidation"),
        trade.get("latest_exit_reason"),
        trade.get("exit_reason"),
        trade.get("data_snapshot_json"),
        trade.get("constraint_results_json"),
        trade.get("model_outputs_json"),
        trade.get("latest_grading_data_json"),
    ]
    return " ".join(_flatten(part) for part in parts).lower()


def classify_trade_failure(
    trade: dict,
    config: dict | None = None,
) -> dict:
    categories: list[str] = []
    reasons: list[str] = []
    warnings: list[str] = []
    text = _context_text(trade if isinstance(trade, dict) else {})
    r_value = calculate_r_multiple(trade if isinstance(trade, dict) else {})
    risk_reward = _safe_float((trade or {}).get("risk_reward"))
    max_drawdown = _safe_float((trade or {}).get("max_drawdown") or (trade or {}).get("latest_max_drawdown"))
    max_gain = _safe_float((trade or {}).get("max_gain") or (trade or {}).get("latest_max_gain"))

    if risk_reward is not None and risk_reward < 2.0:
        categories.append("poor_risk_reward")
        reasons.append("Risk/reward was below the preferred 2.0 threshold.")
    if max_drawdown is not None and max_drawdown <= -1.0 and (max_gain is None or max_gain < 0.5):
        categories.append("stop_too_tight")
        reasons.append("Trade moved quickly against the stop with limited favorable excursion.")
    if risk_reward is not None and risk_reward >= 3.0 and r_value is not None and r_value < 0.5 and max_gain is not None and max_gain > 0:
        categories.append("target_too_aggressive")
        reasons.append("Trade had some favorable movement but did not approach an aggressive target.")
    if r_value is not None and r_value < 0 and "entry" in text:
        categories.append("bad_entry")
        reasons.append("Context references entry quality on a losing trade.")
    if any(token in text for token in ("regime shift", "regime changed", "risk_off", "weak_bull_chop")):
        categories.append("market_regime_shift")
        reasons.append("Context indicates market-regime shift or adverse regime.")
    if any(token in text for token in ("macro", "fomc", "cpi", "jobs report", "fed")):
        categories.append("macro_event_risk")
        reasons.append("Macro-event risk was present in the trade context.")
    if any(token in text for token in ("filing", "8-k", "10-q", "earnings", "sec")):
        categories.append("earnings_or_filing_risk")
        reasons.append("Earnings or filing risk was present in the trade context.")
    if any(token in text for token in ("news", "headline", "downgrade", "investigation")):
        categories.append("news_risk")
        reasons.append("News/headline risk was present in the trade context.")
    if any(token in text for token in ("concentration", "correlation", "sector exposure")):
        categories.append("concentration_risk")
        reasons.append("Concentration or correlation risk was present.")
    if any(token in text for token in ("technical confirmation failed", "timeframe failed", "volume profile failed")):
        categories.append("technical_confirmation_failed")
        reasons.append("Technical confirmation context was weak or failed.")
    if any(token in text for token in ("data quality", "stale", "historical_bar_fallback", "fallback")):
        categories.append("data_quality_issue")
        reasons.append("Data-quality issue or fallback was present.")
    if any(token in text for token in ("slippage", "poor fill", "fill_quality poor", "wide spread")):
        categories.append("slippage_or_fill_issue")
        reasons.append("Slippage/fill-quality risk was present.")
    if any(token in text for token in ("setup decay", "decaying", "disabled_candidate")):
        categories.append("setup_decay")
        reasons.append("Setup decay context was present.")

    if not categories:
        categories.append("unknown")
        warnings.append("No deterministic failure category matched this trade.")

    return {
        "ok": True,
        "trade_id": (trade or {}).get("id"),
        "ticker": (trade or {}).get("ticker"),
        "outcome": (trade or {}).get("outcome") or (trade or {}).get("latest_outcome"),
        "r_multiple": round(r_value, 4) if r_value is not None else None,
        "failure_categories": categories,
        "primary_failure_category": categories[0],
        "reasons": reasons,
        "warnings": warnings,
    }


def analyze_trade_errors(
    trades: list[dict],
    config: dict | None = None,
) -> dict:
    diagnostics = []
    for trade in trades or []:
        if not isinstance(trade, dict):
            continue
        outcome = str(trade.get("outcome") or trade.get("latest_outcome") or "").lower()
        r_value = calculate_r_multiple(trade)
        if outcome == "loss" or (r_value is not None and r_value < 0):
            diagnostics.append(classify_trade_failure(trade, config=config))

    counts = Counter(
        category
        for diagnostic in diagnostics
        for category in diagnostic.get("failure_categories", [])
    )
    top_modes = [
        {"category": category, "count": count}
        for category, count in counts.most_common()
    ]
    recommendations = []
    if counts.get("stop_too_tight"):
        recommendations.append("Review stop placement and ATR/structure fit for trades classified as stop_too_tight.")
    if counts.get("macro_event_risk") or counts.get("news_risk") or counts.get("earnings_or_filing_risk"):
        recommendations.append("Review event-risk filters around macro, news, earnings, and filings.")
    if counts.get("slippage_or_fill_issue"):
        recommendations.append("Review paper fill assumptions and wide-spread/slippage filters.")
    return {
        "ok": True,
        "failure_categories": top_modes,
        "top_failure_modes": top_modes[:5],
        "trade_diagnostics": diagnostics,
        "recommendations": recommendations,
        "warnings": ["No losing paper trades available for error analysis."] if not diagnostics else [],
        "errors": [],
    }
