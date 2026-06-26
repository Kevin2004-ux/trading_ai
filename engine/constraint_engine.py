from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from typing import Any
import math


DEFAULT_STOCK_CONSTRAINTS = {
    "minimum_price": 5.00,
    "minimum_average_volume_20": 1_000_000,
    "minimum_relative_volume": 1.2,
    "require_price_above_sma_20": True,
    "require_price_above_sma_50": True,
    "minimum_risk_reward": 2.0,
    "minimum_atr_percent": 0.015,
    "maximum_atr_percent": 0.12,
    "maximum_days_until_earnings_risk": 7,
    "minimum_score_to_recommend": 80,
}

DEFAULT_OPTION_CONSTRAINTS = {
    "minimum_open_interest": 500,
    "minimum_volume": 100,
    "maximum_bid_ask_spread_percent": 0.15,
    "minimum_days_to_expiration": 14,
    "maximum_days_to_expiration": 56,
    "minimum_risk_reward": 2.0,
    "maximum_iv_rank": 70,
    "require_underlying_passed_stock_constraints": True,
    "minimum_score_to_recommend": 80,
}


def _safe_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    if math.isnan(numeric):
        return None
    return numeric


def _safe_int(value: Any) -> int | None:
    numeric = _safe_float(value)
    if numeric is None:
        return None
    return int(numeric)


def _merge_config(defaults: dict, config: dict | None) -> dict:
    merged = deepcopy(defaults)
    if config:
        merged.update(config)
    return merged


def _normalize_percent(value: Any) -> float | None:
    numeric = _safe_float(value)
    if numeric is None:
        return None
    return numeric / 100.0 if abs(numeric) > 1 else numeric


def _field(candidate: dict, key: str, nested_keys: tuple[str, ...] = ()) -> Any:
    if key in candidate and candidate[key] is not None:
        return candidate[key]

    for nested_key in nested_keys:
        nested_value = candidate.get(nested_key)
        if isinstance(nested_value, dict) and key in nested_value and nested_value[key] is not None:
            return nested_value[key]

    return None


def _build_constraint_result(
    passed: bool,
    actual: Any,
    required: Any,
    message: str,
) -> dict:
    return {
        "passed": bool(passed),
        "actual": actual,
        "required": required,
        "message": message,
    }


def _build_price_above_sma_result(
    *,
    current_price: float | None,
    sma_value: float | None,
    sma_label: str,
    required_enabled: bool,
) -> dict:
    price_is_above = current_price is not None and sma_value is not None and current_price > sma_value
    passed = (not required_enabled) or price_is_above
    if required_enabled:
        required = f"> {sma_value}" if sma_value is not None else f"{sma_label} available and below price"
    else:
        required = "not required by profile"

    if price_is_above:
        message = f"Price is above {sma_label}."
    elif required_enabled:
        message = f"Price is below {sma_label} or {sma_label} is missing."
    elif current_price is None or sma_value is None:
        message = f"{sma_label} comparison is unavailable, but this profile does not require price above {sma_label}."
    else:
        message = f"Price is below {sma_label}, but this profile does not require price above {sma_label}."

    return _build_constraint_result(
        passed,
        current_price,
        required,
        message,
    )


def _score_ratio(actual: float | None, target: float, cap: float = 1.0) -> float:
    if actual is None or target <= 0:
        return 0.0
    return max(0.0, min(actual / target, cap))


def _score_inverse_distance(value: float | None, low: float, high: float) -> float:
    if value is None or high <= low:
        return 0.0
    if low <= value <= high:
        midpoint = (low + high) / 2.0
        spread = max((high - low) / 2.0, 1e-9)
        return max(0.0, 1.0 - (abs(value - midpoint) / spread) * 0.5)
    distance = (low - value) if value < low else (value - high)
    penalty_base = max(high - low, 1e-9)
    return max(0.0, 1.0 - (distance / penalty_base))


def _clamp_score(score: float) -> float:
    return round(max(0.0, min(score, 100.0)), 2)


def build_rejection_reason(failed_constraints: list[str]) -> str:
    if not failed_constraints:
        return ""
    pretty = ", ".join(failed_constraints)
    return f"Rejected because these constraints failed: {pretty}."


def score_stock_candidate(candidate: dict, constraint_results: dict, config: dict | None = None) -> float:
    cfg = _merge_config(DEFAULT_STOCK_CONSTRAINTS, config)

    current_price = _safe_float(_field(candidate, "current_price", ("technical_snapshot",)))
    sma_20 = _safe_float(_field(candidate, "sma_20", ("technical_snapshot",)))
    sma_50 = _safe_float(_field(candidate, "sma_50", ("technical_snapshot",)))
    sma_200 = _safe_float(_field(candidate, "sma_200", ("technical_snapshot",)))
    average_volume_20 = _safe_float(_field(candidate, "average_volume_20", ("technical_snapshot",)))
    relative_volume = _safe_float(_field(candidate, "relative_volume", ("technical_snapshot",)))
    risk_reward = _safe_float(_field(candidate, "risk_reward"))
    atr_fraction = _normalize_percent(_field(candidate, "atr_percent", ("technical_snapshot",)))
    days_until_earnings = _safe_int(_field(candidate, "days_until_earnings"))
    freshness = candidate.get("data_freshness", {})

    trend_components = []
    if current_price is not None and sma_20 not in (None, 0):
        trend_components.append(min(max(current_price / sma_20, 0.0), 1.1) / 1.1)
    if current_price is not None and sma_50 not in (None, 0):
        trend_components.append(min(max(current_price / sma_50, 0.0), 1.1) / 1.1)
    if sma_20 is not None and sma_50 is not None and sma_50 != 0:
        trend_components.append(min(max(sma_20 / sma_50, 0.0), 1.1) / 1.1)
    if current_price is not None and sma_200 not in (None, 0):
        trend_components.append(min(max(current_price / sma_200, 0.0), 1.1) / 1.1)
    trend_score = (sum(trend_components) / len(trend_components)) if trend_components else 0.0

    volume_score = 0.0
    volume_parts = []
    volume_parts.append(_score_ratio(average_volume_20, cfg["minimum_average_volume_20"], cap=1.5) / 1.5)
    volume_parts.append(_score_ratio(relative_volume, cfg["minimum_relative_volume"], cap=1.5) / 1.5)
    volume_parts = [part for part in volume_parts if part is not None]
    if volume_parts:
        volume_score = sum(volume_parts) / len(volume_parts)

    risk_reward_score = _score_ratio(risk_reward, cfg["minimum_risk_reward"] * 1.5, cap=1.0)

    volatility_score = _score_inverse_distance(
        atr_fraction,
        cfg["minimum_atr_percent"],
        cfg["maximum_atr_percent"],
    )

    freshness_score = 0.5
    if isinstance(freshness, dict) and freshness:
        label = str(freshness.get("freshness_label", "unknown")).lower()
        if freshness.get("ok") is False:
            freshness_score = 0.2
        elif label == "fresh":
            freshness_score = 1.0
        elif label == "slightly_stale":
            freshness_score = 0.65
        elif label == "stale":
            freshness_score = 0.1
        else:
            freshness_score = 0.3

    earnings_score = 1.0
    if days_until_earnings is not None:
        max_risk_days = cfg["maximum_days_until_earnings_risk"]
        if days_until_earnings <= max_risk_days:
            earnings_score = 0.0
        elif days_until_earnings <= max_risk_days + 7:
            earnings_score = 0.45
        else:
            earnings_score = 1.0

    final_score = (
        trend_score * 25
        + volume_score * 20
        + risk_reward_score * 20
        + volatility_score * 15
        + freshness_score * 10
        + earnings_score * 10
    )
    return _clamp_score(final_score)


def score_option_candidate(
    option_candidate: dict,
    constraint_results: dict,
    underlying_result: dict | None = None,
    config: dict | None = None,
) -> float:
    cfg = _merge_config(DEFAULT_OPTION_CONSTRAINTS, config)

    bid = _safe_float(_field(option_candidate, "bid"))
    ask = _safe_float(_field(option_candidate, "ask"))
    mid = _safe_float(_field(option_candidate, "mid"))
    if mid is None and bid is not None and ask is not None:
        mid = (bid + ask) / 2.0

    open_interest = _safe_float(_field(option_candidate, "open_interest"))
    volume = _safe_float(_field(option_candidate, "volume"))
    risk_reward = _safe_float(_field(option_candidate, "risk_reward"))
    days_to_expiration = _safe_float(_field(option_candidate, "days_to_expiration"))
    iv_rank = _safe_float(_field(option_candidate, "iv_rank"))

    liquidity_score = 0.0
    liquidity_parts = [
        _score_ratio(open_interest, cfg["minimum_open_interest"] * 2.0, cap=1.0),
        _score_ratio(volume, cfg["minimum_volume"] * 3.0, cap=1.0),
    ]
    liquidity_parts = [part for part in liquidity_parts if part is not None]
    if liquidity_parts:
        liquidity_score = sum(liquidity_parts) / len(liquidity_parts)

    spread_score = 0.0
    spread_percent = None
    if bid is not None and ask is not None and mid not in (None, 0):
        spread_percent = (ask - bid) / mid
        max_spread = cfg["maximum_bid_ask_spread_percent"]
        spread_score = max(0.0, min(1.0, 1.0 - (spread_percent / max_spread)))

    expiration_score = 0.0
    if days_to_expiration is not None:
        expiration_score = _score_inverse_distance(
            days_to_expiration,
            cfg["minimum_days_to_expiration"],
            cfg["maximum_days_to_expiration"],
        )

    risk_reward_score = _score_ratio(risk_reward, cfg["minimum_risk_reward"] * 1.5, cap=1.0)

    iv_score = 0.7
    if iv_rank is not None:
        max_iv_rank = cfg["maximum_iv_rank"]
        iv_score = max(0.0, min(1.0, 1.0 - (iv_rank / max(max_iv_rank, 1))))

    underlying_score = 0.5
    if underlying_result:
        underlying_score = _safe_float(underlying_result.get("score"))
        underlying_score = 0.0 if underlying_score is None else min(max(underlying_score / 100.0, 0.0), 1.0)

    final_score = (
        liquidity_score * 25
        + spread_score * 20
        + expiration_score * 15
        + risk_reward_score * 20
        + iv_score * 10
        + underlying_score * 10
    )
    return _clamp_score(final_score)


def evaluate_stock_constraints(candidate: dict, config: dict | None = None) -> dict:
    cfg = _merge_config(DEFAULT_STOCK_CONSTRAINTS, config)

    current_price = _safe_float(_field(candidate, "current_price", ("technical_snapshot",)))
    sma_20 = _safe_float(_field(candidate, "sma_20", ("technical_snapshot",)))
    sma_50 = _safe_float(_field(candidate, "sma_50", ("technical_snapshot",)))
    average_volume_20 = _safe_float(_field(candidate, "average_volume_20", ("technical_snapshot",)))
    relative_volume = _safe_float(_field(candidate, "relative_volume", ("technical_snapshot",)))
    risk_reward = _safe_float(_field(candidate, "risk_reward"))
    atr_fraction = _normalize_percent(_field(candidate, "atr_percent", ("technical_snapshot",)))
    days_until_earnings = _safe_int(_field(candidate, "days_until_earnings"))

    results = {
        "current_price_present": _build_constraint_result(
            current_price is not None,
            current_price,
            "required",
            "Current price must be present." if current_price is None else "Current price is available.",
        ),
        "minimum_price": _build_constraint_result(
            current_price is not None and current_price >= cfg["minimum_price"],
            current_price,
            cfg["minimum_price"],
            "Price meets minimum threshold." if current_price is not None and current_price >= cfg["minimum_price"] else "Price is below minimum threshold.",
        ),
        "minimum_average_volume_20": _build_constraint_result(
            average_volume_20 is not None and average_volume_20 >= cfg["minimum_average_volume_20"],
            average_volume_20,
            cfg["minimum_average_volume_20"],
            "Average volume meets minimum threshold." if average_volume_20 is not None and average_volume_20 >= cfg["minimum_average_volume_20"] else "Average volume is missing or too low.",
        ),
        "minimum_relative_volume": _build_constraint_result(
            relative_volume is not None and relative_volume >= cfg["minimum_relative_volume"],
            relative_volume,
            cfg["minimum_relative_volume"],
            "Relative volume meets minimum threshold." if relative_volume is not None and relative_volume >= cfg["minimum_relative_volume"] else "Relative volume is missing or too low.",
        ),
        "price_above_sma_20": _build_price_above_sma_result(
            current_price=current_price,
            sma_value=sma_20,
            sma_label="SMA 20",
            required_enabled=bool(cfg["require_price_above_sma_20"]),
        ),
        "price_above_sma_50": _build_price_above_sma_result(
            current_price=current_price,
            sma_value=sma_50,
            sma_label="SMA 50",
            required_enabled=bool(cfg["require_price_above_sma_50"]),
        ),
        "minimum_risk_reward": _build_constraint_result(
            risk_reward is not None and risk_reward >= cfg["minimum_risk_reward"],
            risk_reward,
            cfg["minimum_risk_reward"],
            "Risk/reward meets minimum threshold." if risk_reward is not None and risk_reward >= cfg["minimum_risk_reward"] else "Risk/reward is missing or too low.",
        ),
        "atr_percent_range": _build_constraint_result(
            atr_fraction is not None and cfg["minimum_atr_percent"] <= atr_fraction <= cfg["maximum_atr_percent"],
            atr_fraction,
            {
                "minimum": cfg["minimum_atr_percent"],
                "maximum": cfg["maximum_atr_percent"],
            },
            "ATR percent is within the accepted range." if atr_fraction is not None and cfg["minimum_atr_percent"] <= atr_fraction <= cfg["maximum_atr_percent"] else "ATR percent is missing or outside the accepted range.",
        ),
        "earnings_distance": _build_constraint_result(
            days_until_earnings is None or days_until_earnings > cfg["maximum_days_until_earnings_risk"],
            days_until_earnings,
            f"> {cfg['maximum_days_until_earnings_risk']} days",
            "Earnings date is at a safe distance." if days_until_earnings is None or days_until_earnings > cfg["maximum_days_until_earnings_risk"] else "Earnings event is too close to entry.",
        ),
    }

    failed_constraints = [name for name, result in results.items() if not result["passed"]]
    score = score_stock_candidate(candidate, results, cfg)

    passed = len(failed_constraints) == 0
    if not passed:
        recommendation_status = "rejected"
    elif score >= cfg["minimum_score_to_recommend"]:
        recommendation_status = "recommendable"
    else:
        recommendation_status = "watchlist"

    return {
        "passed": passed,
        "recommendation_status": recommendation_status,
        "score": score,
        "constraint_results": results,
        "failed_constraints": failed_constraints,
        "rejection_reason": build_rejection_reason(failed_constraints),
        "config": cfg,
    }


def evaluate_option_constraints(
    option_candidate: dict,
    underlying_result: dict | None = None,
    config: dict | None = None,
) -> dict:
    cfg = _merge_config(DEFAULT_OPTION_CONSTRAINTS, config)

    bid = _safe_float(_field(option_candidate, "bid"))
    ask = _safe_float(_field(option_candidate, "ask"))
    mid = _safe_float(_field(option_candidate, "mid"))
    if mid is None and bid is not None and ask is not None:
        mid = (bid + ask) / 2.0

    open_interest = _safe_float(_field(option_candidate, "open_interest"))
    volume = _safe_float(_field(option_candidate, "volume"))
    days_to_expiration = _safe_float(_field(option_candidate, "days_to_expiration"))
    risk_reward = _safe_float(_field(option_candidate, "risk_reward"))
    iv_rank = _safe_float(_field(option_candidate, "iv_rank"))

    usable_pricing = bid is not None and ask is not None and mid is not None and mid > 0 and ask >= bid
    spread_percent = None
    if usable_pricing:
        spread_percent = (ask - bid) / mid

    underlying_required = cfg["require_underlying_passed_stock_constraints"]
    underlying_passed = bool(underlying_result and underlying_result.get("passed"))

    results = {
        "pricing_available": _build_constraint_result(
            usable_pricing,
            {"bid": bid, "ask": ask, "mid": mid},
            "bid, ask, and mid pricing required",
            "Option pricing is available." if usable_pricing else "Bid/ask/mid pricing is missing or malformed.",
        ),
        "maximum_bid_ask_spread_percent": _build_constraint_result(
            spread_percent is not None and spread_percent <= cfg["maximum_bid_ask_spread_percent"],
            spread_percent,
            cfg["maximum_bid_ask_spread_percent"],
            "Bid/ask spread is within the accepted limit." if spread_percent is not None and spread_percent <= cfg["maximum_bid_ask_spread_percent"] else "Bid/ask spread is too wide.",
        ),
        "minimum_open_interest": _build_constraint_result(
            open_interest is not None and open_interest >= cfg["minimum_open_interest"],
            open_interest,
            cfg["minimum_open_interest"],
            "Open interest meets minimum threshold." if open_interest is not None and open_interest >= cfg["minimum_open_interest"] else "Open interest is missing or too low.",
        ),
        "minimum_volume": _build_constraint_result(
            volume is not None and volume >= cfg["minimum_volume"],
            volume,
            cfg["minimum_volume"],
            "Option volume meets minimum threshold." if volume is not None and volume >= cfg["minimum_volume"] else "Option volume is missing or too low.",
        ),
        "expiration_window": _build_constraint_result(
            days_to_expiration is not None and cfg["minimum_days_to_expiration"] <= days_to_expiration <= cfg["maximum_days_to_expiration"],
            days_to_expiration,
            {
                "minimum": cfg["minimum_days_to_expiration"],
                "maximum": cfg["maximum_days_to_expiration"],
            },
            "Expiration is within the accepted range." if days_to_expiration is not None and cfg["minimum_days_to_expiration"] <= days_to_expiration <= cfg["maximum_days_to_expiration"] else "Expiration is missing or outside the accepted range.",
        ),
        "minimum_risk_reward": _build_constraint_result(
            risk_reward is not None and risk_reward >= cfg["minimum_risk_reward"],
            risk_reward,
            cfg["minimum_risk_reward"],
            "Risk/reward meets minimum threshold." if risk_reward is not None and risk_reward >= cfg["minimum_risk_reward"] else "Risk/reward is missing or too low.",
        ),
        "maximum_iv_rank": _build_constraint_result(
            iv_rank is None or iv_rank <= cfg["maximum_iv_rank"],
            iv_rank,
            cfg["maximum_iv_rank"],
            "IV rank is acceptable." if iv_rank is None or iv_rank <= cfg["maximum_iv_rank"] else "IV rank is too high.",
        ),
        "underlying_passed_constraints": _build_constraint_result(
            (not underlying_required) or underlying_passed,
            underlying_result.get("passed") if isinstance(underlying_result, dict) else None,
            True if underlying_required else "not required",
            "Underlying stock passed required constraints." if (not underlying_required) or underlying_passed else "Underlying stock constraints are missing or failed.",
        ),
    }

    failed_constraints = [name for name, result in results.items() if not result["passed"]]
    score = score_option_candidate(option_candidate, results, underlying_result, cfg)

    passed = len(failed_constraints) == 0
    if not passed:
        recommendation_status = "rejected"
    elif score >= cfg["minimum_score_to_recommend"]:
        recommendation_status = "recommendable"
    else:
        recommendation_status = "watchlist"

    return {
        "passed": passed,
        "recommendation_status": recommendation_status,
        "score": score,
        "constraint_results": results,
        "failed_constraints": failed_constraints,
        "rejection_reason": build_rejection_reason(failed_constraints),
        "config": cfg,
    }
