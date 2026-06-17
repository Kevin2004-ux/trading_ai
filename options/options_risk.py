from __future__ import annotations

import math
from copy import deepcopy
from typing import Any

from execution.slippage_model import estimate_option_slippage
from options.greeks_monitor import evaluate_option_greeks
from options.iv_rank import evaluate_iv_context


DEFAULT_OPTION_RISK_CONFIG = {
    "minimum_dte": 7,
    "high_risk_dte": 14,
    "maximum_normal_dte": 56,
    "wide_spread_research_threshold": 0.15,
    "wide_spread_block_threshold": 0.25,
    "block_expensive_long_premium": True,
}


def _safe_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    if math.isnan(numeric) or math.isinf(numeric):
        return None
    return numeric


def _safe_int(value: Any) -> int | None:
    numeric = _safe_float(value)
    return int(numeric) if numeric is not None else None


def _merge_config(config: dict | None) -> dict:
    merged = deepcopy(DEFAULT_OPTION_RISK_CONFIG)
    if isinstance(config, dict):
        merged.update(config)
    return merged


def _is_long_premium(candidate: dict) -> bool:
    strategy = str(candidate.get("strategy") or candidate.get("strategy_type") or "long_call").lower()
    direction = str(candidate.get("direction") or "long").lower()
    option_type = str(candidate.get("option_type") or "").lower()
    return direction == "long" and ("long" in strategy or option_type in {"call", "put"})


def _combined_candidate(candidate: dict, option_quote: dict | None) -> dict:
    combined = {}
    if isinstance(candidate, dict):
        combined.update(candidate)
    if isinstance(option_quote, dict):
        combined.update({key: value for key, value in option_quote.items() if value is not None})
    return combined


def evaluate_option_trade_risk(
    candidate: dict,
    option_quote: dict | None = None,
    historical_iv_values: list[float] | None = None,
    config: dict | None = None,
) -> dict:
    cfg = _merge_config(config)
    merged = _combined_candidate(candidate if isinstance(candidate, dict) else {}, option_quote)
    reasons: list[str] = []
    warnings: list[str] = []
    errors: list[str] = []

    bid = _safe_float(merged.get("bid"))
    ask = _safe_float(merged.get("ask"))
    mid = _safe_float(merged.get("mid"))
    if mid is None and bid is not None and ask is not None:
        mid = round((bid + ask) / 2.0, 4)
        merged["mid"] = mid
    dte = _safe_int(merged.get("days_to_expiration"))
    current_iv = _safe_float(merged.get("implied_volatility") or merged.get("iv"))

    iv_context = evaluate_iv_context(
        current_iv,
        historical_iv_values=historical_iv_values,
        config={
            "iv_rank": merged.get("iv_rank"),
            "iv_percentile": merged.get("iv_percentile"),
            "lookback_days": (config or {}).get("lookback_days", 252) if isinstance(config, dict) else 252,
        },
    )
    greeks = evaluate_option_greeks(merged, config=config)
    fill = estimate_option_slippage(merged, option_quote=merged, config=config)

    spread_percent = _safe_float(fill.get("spread_percent"))
    spread_quality = fill.get("fill_quality", "unavailable")
    fill_quality = fill.get("fill_quality", "unavailable")
    risk_multiplier = 1.0
    status = "approved"

    if bid is None or ask is None or mid is None or ask < bid:
        status = "blocked"
        errors.append("No usable bid/ask quote is available.")
    if not iv_context.get("ok"):
        status = "blocked"
        errors.append("Implied volatility context is unavailable.")
    if not greeks.get("ok") or greeks.get("greeks_quality") not in {"good", "usable"}:
        status = "blocked"
        errors.append("Usable Greeks are unavailable.")

    if dte is None:
        status = "blocked"
        errors.append("Days to expiration is required.")
    elif dte < cfg["minimum_dte"]:
        status = "blocked"
        errors.append("DTE under 7 is blocked by default.")
    elif dte < cfg["high_risk_dte"]:
        if status != "blocked":
            status = "research_only"
        risk_multiplier *= 0.5
        warnings.append("DTE is 7-14 days; option risk is elevated and size should be reduced.")
    elif dte <= cfg["maximum_normal_dte"]:
        reasons.append("DTE is inside the normal 14-56 day research window.")
    else:
        if status != "blocked":
            status = "research_only"
        risk_multiplier *= 0.75
        warnings.append("DTE is outside the normal 14-56 day window.")

    if spread_percent is None:
        status = "blocked"
        errors.append("Spread percent is unavailable.")
    elif spread_percent > cfg["wide_spread_block_threshold"]:
        status = "blocked"
        errors.append("Bid/ask spread is too wide for option eligibility.")
    elif spread_percent > cfg["wide_spread_research_threshold"]:
        if status != "blocked":
            status = "research_only"
        risk_multiplier *= 0.75
        warnings.append("Bid/ask spread is wide; option is research-only.")

    iv_label = str(iv_context.get("iv_context", "unknown")).lower()
    if _is_long_premium(merged):
        if iv_label == "expensive" and cfg["block_expensive_long_premium"]:
            status = "blocked"
            errors.append("Expensive IV blocks long-premium option recommendations.")
        elif iv_label == "elevated":
            if status != "blocked":
                status = "research_only"
            risk_multiplier *= 0.75
            warnings.append("Elevated IV is less favorable for long-premium trades.")
        elif iv_label in {"cheap", "normal"}:
            reasons.append("IV context is favorable for long-premium research.")

    if fill_quality not in {"good", "usable"}:
        if status != "blocked":
            status = "research_only"
        warnings.append("Fill quality is not good/usable.")

    approved = status == "approved"
    options_research_status = "paper_eligible" if approved else status
    return {
        "ok": not errors,
        "approved": approved,
        "status": status,
        "iv_context": iv_context,
        "greeks": greeks,
        "spread_quality": spread_quality,
        "fill_quality": fill_quality,
        "days_to_expiration": dte,
        "risk_multiplier": round(max(0.0, min(risk_multiplier, 1.0)), 4),
        "options_research_status": options_research_status,
        "reasons": reasons,
        "warnings": warnings + list(iv_context.get("warnings", [])) + list(greeks.get("warnings", [])) + list(fill.get("warnings", [])),
        "errors": errors + list(iv_context.get("errors", [])) + list(greeks.get("errors", [])) + ([fill.get("error")] if fill.get("error") else []),
    }

