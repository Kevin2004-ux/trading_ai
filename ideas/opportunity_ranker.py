from __future__ import annotations

from copy import deepcopy
from typing import Any
import math

from engine.constraint_engine import DEFAULT_STOCK_CONSTRAINTS
from .data_failures import (
    has_trade_prices,
    has_usable_technical_snapshot,
    is_data_failure_candidate,
)


STOCK_OPPORTUNITY_SCORE_VERSION = "stock_opportunity_v1"

DEFAULT_STOCK_OPPORTUNITY_WEIGHTS = {
    "engine_core": 0.35,
    "qualification_fit": 0.20,
    "technical_confirmation": 0.15,
    "relative_strength": 0.10,
    "risk_reward": 0.10,
    "statistical_edge": 0.05,
    "catalyst_context": 0.03,
    "data_confidence": 0.02,
}


def _as_dict(value: Any) -> dict:
    return value if isinstance(value, dict) else {}


def _as_list(value: Any) -> list:
    return value if isinstance(value, list) else []


def _safe_float(value: Any) -> float | None:
    try:
        if value is None or value == "":
            return None
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    return None if math.isnan(numeric) else numeric


def _clamp(value: float | None, minimum: float = 0.0, maximum: float = 100.0) -> float:
    if value is None:
        return minimum
    return round(max(minimum, min(maximum, value)), 2)


def _field(candidate: dict, key: str) -> Any:
    if candidate.get(key) is not None:
        return candidate.get(key)
    for nested_key in ("technical_snapshot", "metrics", "data"):
        nested = candidate.get(nested_key)
        if isinstance(nested, dict) and nested.get(key) is not None:
            return nested.get(key)
    return None


def _unique_texts(values: list[Any]) -> list[str]:
    seen: set[str] = set()
    unique: list[str] = []
    for value in values:
        text = str(value).strip() if value is not None else ""
        if not text:
            continue
        key = text.lower()
        if key in seen:
            continue
        seen.add(key)
        unique.append(text)
    return unique


def _extend_texts(rows: list[str], value: Any) -> None:
    if isinstance(value, str) and value.strip():
        rows.append(value.strip())
    elif isinstance(value, list):
        for item in value:
            if isinstance(item, str) and item.strip():
                rows.append(item.strip())


def _component(score: float | None = None, weight: float = 0.0, available: bool = False, evidence: list[Any] | None = None) -> dict:
    return {
        "score": _clamp(score if available else 0.0),
        "weight": round(float(weight), 6),
        "available": bool(available),
        "evidence": _unique_texts(evidence or []),
    }


def _empty_components(weights: dict[str, float]) -> dict:
    return {name: _component(weight=weight) for name, weight in weights.items()}


def _normalize_weights(config: dict | None) -> dict[str, float]:
    raw_config = _as_dict(config)
    raw_weights = raw_config.get("weights") or raw_config.get("component_weights")
    if raw_weights is None:
        return deepcopy(DEFAULT_STOCK_OPPORTUNITY_WEIGHTS)
    if not isinstance(raw_weights, dict):
        return deepcopy(DEFAULT_STOCK_OPPORTUNITY_WEIGHTS)

    merged = deepcopy(DEFAULT_STOCK_OPPORTUNITY_WEIGHTS)
    for key, value in raw_weights.items():
        if key not in merged:
            continue
        numeric = _safe_float(value)
        if numeric is None or numeric < 0:
            return deepcopy(DEFAULT_STOCK_OPPORTUNITY_WEIGHTS)
        merged[key] = numeric

    total = sum(merged.values())
    if total <= 0:
        return deepcopy(DEFAULT_STOCK_OPPORTUNITY_WEIGHTS)
    return {key: value / total for key, value in merged.items()}


def _actionability_status(candidate: dict) -> str:
    status = str(candidate.get("recommendation_status") or candidate.get("status") or candidate.get("bucket") or "").lower()
    if status in {"recommendable", "paper_eligible"}:
        return "paper_eligible"
    if status == "watchlist":
        return "watchlist"
    if candidate.get("passed") is True and status not in {"rejected", "blocked"}:
        return "watchlist"
    return "blocked"


def _constraint_results(candidate: dict) -> dict:
    results = _as_dict(candidate.get("constraint_results"))
    if results:
        return results
    return {}


def _constraint_value(candidate: dict, constraint: str, key: str) -> Any:
    result = _as_dict(_constraint_results(candidate).get(constraint))
    if result.get(key) is not None:
        return result.get(key)
    return None


def _config(candidate: dict, config: dict | None) -> dict:
    merged = deepcopy(DEFAULT_STOCK_CONSTRAINTS)
    candidate_config = _as_dict(candidate.get("config"))
    merged.update(candidate_config)
    user_config = _as_dict(config)
    for key, value in user_config.items():
        if key in merged:
            merged[key] = value
    return merged


def _required_number(candidate: dict, cfg: dict, constraint: str, config_key: str) -> float | None:
    required = _constraint_value(candidate, constraint, "required")
    numeric = _safe_float(required)
    if numeric is not None:
        return numeric
    return _safe_float(cfg.get(config_key))


def _price_above_required(candidate: dict, constraint: str, fallback_key: str) -> float | None:
    required = _constraint_value(candidate, constraint, "required")
    if isinstance(required, str):
        cleaned = required.replace(">", "").strip()
        numeric = _safe_float(cleaned)
        if numeric is not None:
            return numeric
    return _safe_float(_field(candidate, fallback_key))


def _gap_row(constraint: str, actual: Any, required: Any, message: str | None = None) -> dict:
    actual_number = _safe_float(actual)
    required_number = _safe_float(required)
    gap = None
    gap_percent = None
    severity = "unknown"
    if actual_number is not None and required_number is not None:
        gap = round(max(required_number - actual_number, 0.0), 4)
        if required_number:
            gap_percent = round((gap / abs(required_number)) * 100.0, 2)
        if gap_percent is not None:
            if gap_percent <= 10:
                severity = "near"
            elif gap_percent <= 30:
                severity = "moderate"
            else:
                severity = "far"
    return {
        "constraint": constraint,
        "actual": actual,
        "required": required,
        "gap": gap,
        "gap_percent": gap_percent,
        "severity": severity,
        "message": message or f"{constraint} did not meet the required threshold.",
    }


def _score_minimum(actual: float | None, required: float | None) -> float | None:
    if actual is None or required is None or required <= 0:
        return None
    if actual >= required:
        return 100.0
    return _clamp((actual / required) * 100.0)


def _score_maximum(actual: float | None, maximum: float | None) -> float | None:
    if actual is None or maximum is None or maximum <= 0:
        return None
    if actual <= maximum:
        return 100.0
    overage = actual - maximum
    return _clamp(100.0 - (overage / maximum) * 100.0)


def _score_range(actual: float | None, minimum: float | None, maximum: float | None) -> float | None:
    if actual is None or minimum is None or maximum is None or maximum <= minimum:
        return None
    if minimum <= actual <= maximum:
        return 100.0
    if actual < minimum:
        return _score_minimum(actual, minimum)
    return _score_maximum(actual, maximum)


def _constraint_passed(candidate: dict, constraint: str) -> bool | None:
    result = _as_dict(_constraint_results(candidate).get(constraint))
    if "passed" in result:
        return bool(result.get("passed"))
    return None


def _qualification_fit(candidate: dict, cfg: dict) -> tuple[float | None, list[str], list[dict]]:
    parts: list[float] = []
    evidence: list[str] = []
    gaps: list[dict] = []

    checks = (
        ("current_price_present", _safe_float(_field(candidate, "current_price")), 0.01, "Current price is available.", "Current price must be present."),
        ("minimum_price", _safe_float(_field(candidate, "current_price")), _required_number(candidate, cfg, "minimum_price", "minimum_price"), "Price meets minimum threshold.", "Price is below minimum threshold."),
        ("minimum_average_volume_20", _safe_float(_field(candidate, "average_volume_20")), _required_number(candidate, cfg, "minimum_average_volume_20", "minimum_average_volume_20"), "Average volume meets minimum threshold.", "Average volume must improve."),
        ("minimum_relative_volume", _safe_float(_field(candidate, "relative_volume")), _required_number(candidate, cfg, "minimum_relative_volume", "minimum_relative_volume"), "Relative volume meets minimum threshold.", "Relative volume is below the required threshold."),
        ("minimum_risk_reward", _safe_float(_field(candidate, "risk_reward")), _required_number(candidate, cfg, "minimum_risk_reward", "minimum_risk_reward"), "Risk/reward meets minimum threshold.", "Risk/reward is below the required threshold."),
        ("minimum_score_to_recommend", _safe_float(candidate.get("score")), _safe_float(cfg.get("minimum_score_to_recommend")), "Deterministic engine score meets recommendation threshold.", "Deterministic engine score is below recommendation threshold."),
    )

    for constraint, actual, required, pass_message, fail_message in checks:
        score = _score_minimum(actual, required)
        if score is None:
            continue
        parts.append(score)
        if score >= 100:
            evidence.append(pass_message)
        else:
            gaps.append(_gap_row(constraint, actual, required, f"{fail_message} Actual {actual}; required {required}."))

    current_price = _safe_float(_field(candidate, "current_price"))
    for constraint, sma_key, label in (
        ("price_above_sma_20", "sma_20", "SMA 20"),
        ("price_above_sma_50", "sma_50", "SMA 50"),
    ):
        required = _price_above_required(candidate, constraint, sma_key)
        if current_price is None or required is None:
            continue
        score = 100.0 if current_price > required else _score_minimum(current_price, required)
        parts.append(score or 0.0)
        if current_price > required:
            evidence.append(f"Price is above {label}.")
        else:
            gaps.append(_gap_row(constraint, current_price, required, f"Price is {current_price}; it must reclaim {label} at {required}."))

    atr = _safe_float(_field(candidate, "atr_percent"))
    if atr is not None and abs(atr) > 1:
        atr = atr / 100.0
    min_atr = _safe_float(cfg.get("minimum_atr_percent"))
    max_atr = _safe_float(cfg.get("maximum_atr_percent"))
    atr_score = _score_range(atr, min_atr, max_atr)
    if atr_score is not None:
        parts.append(atr_score)
        if atr_score >= 100:
            evidence.append("ATR percent is within accepted swing-trading range.")
        elif min_atr is not None and atr is not None and atr < min_atr:
            gaps.append(_gap_row("minimum_atr_percent", atr, min_atr, "ATR percent is below the configured minimum."))
        elif max_atr is not None and atr is not None and atr > max_atr:
            gaps.append(_gap_row("maximum_atr_percent", atr, max_atr, "ATR percent is above the configured maximum."))

    days_until_earnings = _safe_float(_field(candidate, "days_until_earnings"))
    max_earnings_risk = _safe_float(cfg.get("maximum_days_until_earnings_risk"))
    if days_until_earnings is not None and max_earnings_risk is not None:
        if days_until_earnings > max_earnings_risk:
            parts.append(100.0)
            evidence.append("Earnings risk window is clear.")
        else:
            parts.append(0.0)
            gaps.append(_gap_row("earnings_risk", days_until_earnings, f"> {max_earnings_risk} days", "Earnings event is inside the configured risk window."))

    technical = _as_dict(candidate.get("technical_confirmation_summary"))
    if str(technical.get("status") or "").lower() == "rejected":
        parts.append(0.0)
        gaps.append(_gap_row("technical_confirmation_rejected", technical.get("status"), "not rejected", "Technical confirmation rejected this setup."))

    for failed in _as_list(candidate.get("failed_constraints")):
        normalized = str(failed).lower()
        if any(token in normalized for token in ("portfolio", "concentration", "macro", "circuit")):
            parts.append(0.0)
            gaps.append(_gap_row(str(failed), None, None, f"{failed} blocked actionability."))

    if not parts:
        return None, evidence, gaps
    return sum(parts) / len(parts), evidence, gaps


def _technical_confirmation(candidate: dict) -> tuple[float | None, list[str], list[str]]:
    summaries = []
    for key in ("technical_confirmation_summary", "volume_profile_confirmation", "timeframe_confirmation"):
        value = _as_dict(candidate.get(key))
        if value:
            summaries.append(value)
    if not summaries:
        return None, [], []

    status_scores = {
        "confirmed": 100.0,
        "pass": 100.0,
        "passed": 100.0,
        "neutral": 65.0,
        "warning": 45.0,
        "watchlist": 45.0,
        "rejected": 10.0,
        "fail": 10.0,
        "failed": 10.0,
    }
    scores: list[float] = []
    evidence: list[str] = []
    risks: list[str] = []
    for summary in summaries:
        status = str(summary.get("status") or summary.get("confirmation_status") or "").lower()
        if status in status_scores:
            scores.append(status_scores[status])
            evidence.append(f"Technical confirmation status: {status}.")
        adjustment = _safe_float(summary.get("score_adjustment"))
        if adjustment is not None:
            scores.append(_clamp(65.0 + adjustment * 5.0))
            evidence.append(f"Technical score adjustment: {adjustment}.")
        _extend_texts(evidence, summary.get("reasons"))
        _extend_texts(risks, summary.get("warnings"))
    return (sum(scores) / len(scores) if scores else None), evidence, risks


def _relative_strength(candidate: dict) -> tuple[float | None, list[str], list[str]]:
    context = _as_dict(candidate.get("relative_strength_context"))
    if not context:
        return None, [], []
    label = str(context.get("relative_strength_label") or context.get("label") or "").lower()
    label_scores = {
        "market_leader": 100.0,
        "outperforming": 82.0,
        "neutral": 55.0,
        "underperforming": 30.0,
        "market_laggard": 10.0,
    }
    score = label_scores.get(label)
    numeric = _safe_float(context.get("relative_strength_score") or context.get("score") or context.get("percentile"))
    if numeric is not None:
        score = _clamp(numeric if numeric > 1 else numeric * 100.0)
    evidence = [f"Relative strength: {label}."] if label else []
    risks = []
    if label in {"underperforming", "market_laggard"}:
        risks.append(f"Relative strength is {label}.")
    return score, evidence, risks


def _risk_reward(candidate: dict, cfg: dict) -> tuple[float | None, list[str], list[str], list[dict]]:
    rr = _safe_float(_field(candidate, "risk_reward"))
    required = _safe_float(cfg.get("minimum_risk_reward"))
    if rr is None or required is None or required <= 0:
        return None, [], [], []
    score = _clamp((rr / (required * 1.5)) * 100.0)
    evidence = [f"Risk/reward is {rr:.2f} versus required {required:.2f}."] if rr >= required else []
    risks = [] if rr >= required else [f"Risk/reward is {rr:.2f}, below required {required:.2f}."]
    gaps = [] if rr >= required else [_gap_row("minimum_risk_reward", rr, required, f"Risk/reward is {rr:.2f}; at least {required:.2f} is required.")]
    return score, evidence, risks, gaps


def _statistical_edge(candidate: dict) -> tuple[float | None, list[str], list[str]]:
    context = _as_dict(candidate.get("statistical_context"))
    if not context:
        return None, [], []
    setup = _as_dict(context.get("setup_performance"))
    ticker = _as_dict(context.get("ticker_history"))
    sample_size = _safe_float(setup.get("sample_size") or ticker.get("closed_trades") or ticker.get("total_recommendations"))
    expectancy = _safe_float(setup.get("expectancy") or ticker.get("expectancy"))
    win_rate = _safe_float(setup.get("win_rate") or ticker.get("win_rate"))
    if sample_size is None or sample_size < 5:
        return 45.0, [], ["Statistical edge sample is too small to treat as proven."]
    if expectancy is not None:
        score = _clamp(50.0 + expectancy * 100.0)
        evidence = [f"Historical setup expectancy is {expectancy:.2f} over {int(sample_size)} samples."] if expectancy > 0 else []
        risks = [f"Historical setup expectancy is negative at {expectancy:.2f}."] if expectancy < 0 else []
        return score, evidence, risks
    if win_rate is not None:
        normalized = win_rate if win_rate <= 1 else win_rate / 100.0
        score = _clamp(normalized * 100.0)
        evidence = [f"Historical win rate is {normalized:.0%} over {int(sample_size)} samples."] if normalized >= 0.5 else []
        risks = [f"Historical win rate is weak at {normalized:.0%}."] if normalized < 0.5 else []
        return score, evidence, risks
    return None, [], []


def _catalyst_context(candidate: dict) -> tuple[float | None, list[str], list[str]]:
    context = _as_dict(candidate.get("catalyst_context") or candidate.get("catalyst_summary"))
    if not context:
        return None, [], []
    label = str(context.get("sentiment") or context.get("label") or context.get("catalyst_label") or "").lower()
    score = _safe_float(context.get("score") or context.get("catalyst_score"))
    if score is not None:
        score = _clamp(score if score > 1 else score * 100.0)
    elif label in {"positive", "bullish", "strong"}:
        score = 85.0
    elif label in {"neutral", "mixed"}:
        score = 55.0
    elif label in {"negative", "bearish", "weak"}:
        score = 25.0
    else:
        score = 55.0
    evidence = []
    risks = []
    summary = context.get("summary") or context.get("reason")
    if label in {"positive", "bullish", "strong"}:
        evidence.append(f"Catalyst context is {label}.")
    elif label in {"negative", "bearish", "weak"}:
        risks.append(f"Catalyst context is {label}.")
    _extend_texts(evidence, summary)
    _extend_texts(risks, context.get("risks"))
    return score, evidence, risks


def _data_confidence(candidate: dict) -> tuple[float, list[str], list[str]]:
    data_quality = _as_dict(candidate.get("data_quality"))
    freshness = _as_dict(candidate.get("data_freshness"))
    score = 70.0
    evidence: list[str] = []
    risks: list[str] = []

    label = str(data_quality.get("quality_label") or "").lower()
    if label in {"excellent", "good", "fresh"}:
        score += 20
        evidence.append(f"Data quality is {label}.")
    elif label in {"usable", "usable_with_warnings", "slightly_stale"}:
        score += 5
        risks.append(f"Data quality has warnings: {label}.")
    elif label in {"poor", "stale"}:
        score -= 35
        risks.append(f"Data quality is {label}.")
    elif label == "unavailable":
        score = 0
        risks.append("Data quality is unavailable.")

    freshness_label = str(freshness.get("freshness_label") or "").lower()
    if freshness.get("is_stale") is True or freshness_label == "stale":
        score -= 30
        risks.append("Market data freshness is stale.")
    elif freshness_label in {"fresh", "latest_completed_session"}:
        score += 10
        evidence.append(f"Data freshness is {freshness_label}.")

    if has_trade_prices(candidate):
        score += 5
        evidence.append("Usable price fields are present.")
    if has_usable_technical_snapshot(candidate):
        score += 5
        evidence.append("Usable technical snapshot is present.")
    if candidate.get("partial_results") is True:
        score -= 15
        risks.append("Candidate was produced from partial results.")
    _extend_texts(risks, data_quality.get("warnings"))
    return _clamp(score), evidence, risks


def _confirmation_for_constraint(constraint: str) -> str:
    normalized = str(constraint or "").lower()
    if "minimum_relative_volume" in normalized or "relative_volume" in normalized:
        return "Relative volume must improve to the required threshold."
    if "price_above_sma_20" in normalized or "sma_20" in normalized:
        return "Price must reclaim SMA 20."
    if "price_above_sma_50" in normalized or "sma_50" in normalized:
        return "Price must reclaim SMA 50."
    if "minimum_risk_reward" in normalized or "risk_reward" in normalized:
        return "Risk/reward must improve to the required threshold."
    if "minimum_score_to_recommend" in normalized or "minimum_score" in normalized:
        return "The deterministic engine score must improve."
    if "technical_confirmation_rejected" in normalized or "technical_confirmation" in normalized:
        return "Technical confirmation must improve."
    if "earnings" in normalized:
        return "The configured earnings-risk window must pass or be explicitly resolved."
    if "portfolio" in normalized or "concentration" in normalized:
        return "Portfolio risk must clear."
    if "macro" in normalized or "regime" in normalized:
        return "Macro or market-regime risk must clear."
    return f"{constraint} must improve."


def _base_result(weights: dict[str, float], actionability_status: str) -> dict:
    return {
        "rankable": False,
        "opportunity_score": None,
        "score_version": STOCK_OPPORTUNITY_SCORE_VERSION,
        "actionability_status": actionability_status,
        "components": _empty_components(weights),
        "data_confidence": 0.0,
        "why_ranked": [],
        "key_risks": [],
        "confirmation_needed": [],
        "qualification_gaps": [],
    }


def score_stock_opportunity(candidate: dict, config: dict | None = None) -> dict:
    candidate = candidate if isinstance(candidate, dict) else {}
    weights = _normalize_weights(config)
    cfg = _config(candidate, config)
    actionability_status = _actionability_status(candidate)
    result = _base_result(weights, actionability_status)

    engine_score = _safe_float(candidate.get("score"))
    has_essential_market_data = has_trade_prices(candidate) or has_usable_technical_snapshot(candidate) or engine_score is not None
    if is_data_failure_candidate(candidate) or not has_essential_market_data:
        result["key_risks"] = ["Essential market data is unavailable; this stock cannot be ranked."]
        return result

    components: dict[str, dict] = {}
    why_ranked: list[str] = []
    key_risks: list[str] = []
    qualification_gaps: list[dict] = []

    if engine_score is not None:
        components["engine_core"] = _component(engine_score, weights["engine_core"], True, [f"Existing deterministic engine score is {engine_score:.2f}."])
    else:
        components["engine_core"] = _component(weight=weights["engine_core"])

    qualification_score, qualification_evidence, gaps = _qualification_fit(candidate, cfg)
    qualification_gaps.extend(gaps)
    components["qualification_fit"] = _component(qualification_score, weights["qualification_fit"], qualification_score is not None, qualification_evidence)

    technical_score, technical_evidence, technical_risks = _technical_confirmation(candidate)
    components["technical_confirmation"] = _component(technical_score, weights["technical_confirmation"], technical_score is not None, technical_evidence)
    key_risks.extend(technical_risks)

    relative_score, relative_evidence, relative_risks = _relative_strength(candidate)
    components["relative_strength"] = _component(relative_score, weights["relative_strength"], relative_score is not None, relative_evidence)
    key_risks.extend(relative_risks)

    risk_reward_score, risk_reward_evidence, risk_reward_risks, risk_reward_gaps = _risk_reward(candidate, cfg)
    components["risk_reward"] = _component(risk_reward_score, weights["risk_reward"], risk_reward_score is not None, risk_reward_evidence)
    key_risks.extend(risk_reward_risks)
    qualification_gaps.extend(risk_reward_gaps)

    statistical_score, statistical_evidence, statistical_risks = _statistical_edge(candidate)
    components["statistical_edge"] = _component(statistical_score, weights["statistical_edge"], statistical_score is not None, statistical_evidence)
    key_risks.extend(statistical_risks)

    catalyst_score, catalyst_evidence, catalyst_risks = _catalyst_context(candidate)
    components["catalyst_context"] = _component(catalyst_score, weights["catalyst_context"], catalyst_score is not None, catalyst_evidence)
    key_risks.extend(catalyst_risks)

    data_confidence, data_evidence, data_risks = _data_confidence(candidate)
    components["data_confidence"] = _component(data_confidence, weights["data_confidence"], True, data_evidence)
    key_risks.extend(data_risks)

    for key in ("why_selected", "why_this_profile_matched", "selection_reason", "thesis"):
        _extend_texts(why_ranked, candidate.get(key))
    for component in components.values():
        if component["available"] and component["score"] >= 65:
            why_ranked.extend(component.get("evidence", []))

    for failed in _as_list(candidate.get("failed_constraints")):
        key_risks.append(str(failed))
    if candidate.get("downgrade_reason"):
        key_risks.append(str(candidate["downgrade_reason"]))
    _extend_texts(key_risks, candidate.get("invalidation"))
    _extend_texts(key_risks, _as_dict(candidate.get("technical_confirmation_summary")).get("warnings"))

    confirmations = [_confirmation_for_constraint(gap["constraint"]) for gap in qualification_gaps]
    confirmations.extend(_confirmation_for_constraint(item) for item in _as_list(candidate.get("failed_constraints")))

    available_weight = sum(component["weight"] for component in components.values() if component["available"])
    if available_weight <= 0:
        result["key_risks"] = ["No structured scoring components were available."]
        return result

    score = sum(component["score"] * component["weight"] for component in components.values() if component["available"]) / available_weight

    result.update(
        {
            "rankable": True,
            "opportunity_score": _clamp(score),
            "components": components,
            "data_confidence": data_confidence,
            "why_ranked": _unique_texts(why_ranked),
            "key_risks": _unique_texts(key_risks),
            "confirmation_needed": _unique_texts(confirmations),
            "qualification_gaps": qualification_gaps,
        }
    )
    return result
