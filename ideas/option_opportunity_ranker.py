from __future__ import annotations

from copy import deepcopy
from typing import Any
import math

from engine.constraint_engine import DEFAULT_OPTION_CONSTRAINTS


OPTION_OPPORTUNITY_SCORE_VERSION = "option_opportunity_v1"

DEFAULT_OPTION_OPPORTUNITY_WEIGHTS = {
    "underlying_quality": 0.25,
    "contract_liquidity": 0.20,
    "spread_and_fill": 0.15,
    "expiration_fit": 0.10,
    "breakeven_realism": 0.10,
    "risk_reward": 0.10,
    "volatility_context": 0.05,
    "greeks_quality": 0.05,
}

ESSENTIAL_OPTION_RANKABILITY_FIELDS = (
    "underlying_ticker",
    "option_contract",
    "option_type",
    "strike",
    "expiration",
    "days_to_expiration",
    "bid",
    "ask",
    "mid",
    "underlying_price",
)


def _as_dict(value: Any) -> dict:
    return value if isinstance(value, dict) else {}


def _as_list(value: Any) -> list:
    return value if isinstance(value, list) else []


def _safe_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    return numeric if math.isfinite(numeric) else None


def _safe_int(value: Any) -> int | None:
    numeric = _safe_float(value)
    return int(numeric) if numeric is not None else None


def _clamp(value: float | None, minimum: float = 0.0, maximum: float = 100.0) -> float:
    if value is None:
        return minimum
    return round(max(minimum, min(maximum, value)), 2)


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
    if not isinstance(raw_weights, dict):
        return deepcopy(DEFAULT_OPTION_OPPORTUNITY_WEIGHTS)

    merged = deepcopy(DEFAULT_OPTION_OPPORTUNITY_WEIGHTS)
    for key, value in raw_weights.items():
        if key not in merged:
            continue
        numeric = _safe_float(value)
        if numeric is None or numeric < 0:
            return deepcopy(DEFAULT_OPTION_OPPORTUNITY_WEIGHTS)
        merged[key] = numeric

    total = sum(merged.values())
    if total <= 0:
        return deepcopy(DEFAULT_OPTION_OPPORTUNITY_WEIGHTS)
    return {key: value / total for key, value in merged.items()}


def _field(candidate: dict, key: str) -> Any:
    if candidate.get(key) is not None:
        return candidate.get(key)
    for nested_key in ("metrics", "data", "technical_snapshot", "underlying_view", "underlying_candidate"):
        nested = candidate.get(nested_key)
        if isinstance(nested, dict) and nested.get(key) is not None:
            return nested.get(key)
    return None


def _underlying_field(option_candidate: dict, underlying_candidate: dict | None, key: str) -> Any:
    if isinstance(underlying_candidate, dict):
        raw = _as_dict(underlying_candidate.get("raw_candidate")) or underlying_candidate
        if raw.get(key) is not None:
            return raw.get(key)
        if underlying_candidate.get(key) is not None:
            return underlying_candidate.get(key)
    return _field(option_candidate, key)


def _underlying_ticker(option_candidate: dict, underlying_candidate: dict | None) -> str:
    value = (
        option_candidate.get("underlying_ticker")
        or _underlying_field(option_candidate, underlying_candidate, "ticker")
        or option_candidate.get("underlying")
    )
    return str(value or "").strip().upper()


def _option_contract(option_candidate: dict, underlying_ticker: str) -> str:
    contract = str(option_candidate.get("option_contract") or "").strip().upper()
    if contract:
        return contract
    ticker = str(option_candidate.get("ticker") or "").strip().upper()
    return ticker if ticker and ticker != underlying_ticker else ""


def _mid(option_candidate: dict) -> float | None:
    mid = _safe_float(option_candidate.get("mid"))
    bid = _safe_float(option_candidate.get("bid"))
    ask = _safe_float(option_candidate.get("ask"))
    if mid is None and bid is not None and ask is not None:
        mid = round((bid + ask) / 2.0, 4)
    return mid


def _underlying_price(option_candidate: dict, underlying_candidate: dict | None) -> float | None:
    return (
        _safe_float(option_candidate.get("underlying_price"))
        or _safe_float(_underlying_field(option_candidate, underlying_candidate, "current_price"))
        or _safe_float(_underlying_field(option_candidate, underlying_candidate, "entry_price"))
    )


def _actionability_status(candidate: dict) -> str:
    risk = _as_dict(candidate.get("option_trade_risk") or candidate.get("risk"))
    evaluation = _as_dict(candidate.get("evaluation"))
    status = str(
        candidate.get("actionability_status")
        or candidate.get("recommendation_status")
        or candidate.get("status")
        or risk.get("options_research_status")
        or risk.get("status")
        or evaluation.get("status")
        or ""
    ).lower()
    if status in {"recommendable", "paper_eligible", "approved"}:
        return "paper_eligible"
    if status in {"research_only", "watchlist"}:
        return "research_only"
    return "blocked"


def _score_minimum(actual: float | None, required: float | None) -> float | None:
    if actual is None or required is None or required <= 0:
        return None
    return 100.0 if actual >= required else _clamp((actual / required) * 100.0)


def _score_maximum(actual: float | None, maximum: float | None) -> float | None:
    if actual is None or maximum is None or maximum <= 0:
        return None
    if actual <= maximum:
        return 100.0
    return _clamp(100.0 - ((actual - maximum) / maximum) * 100.0)


def _gap_row(constraint: str, actual: Any, required: Any, message: str | None = None) -> dict:
    actual_number = _safe_float(actual)
    required_number = _safe_float(required)
    gap = None
    gap_percent = None
    severity = "unknown"
    if actual_number is not None and required_number is not None:
        if required_number == 0:
            gap = 0.0 if actual_number == 0 else actual_number
        elif actual_number < required_number:
            gap = round(required_number - actual_number, 4)
        else:
            gap = round(actual_number - required_number, 4)
        gap_percent = round(abs(gap / required_number) * 100.0, 2) if required_number else None
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


def _constraint_gaps(candidate: dict) -> list[dict]:
    gaps: list[dict] = []
    constraint_results = _as_dict(candidate.get("constraint_results"))
    for name, result in constraint_results.items():
        row = _as_dict(result)
        if row.get("passed") is True:
            continue
        gaps.append(_gap_row(str(name), row.get("actual"), row.get("required"), row.get("message")))

    risk = _as_dict(candidate.get("option_trade_risk") or candidate.get("risk"))
    for error in _as_list(risk.get("errors")):
        gaps.append(_gap_row("option_trade_risk", None, None, str(error)))
    for warning in _as_list(risk.get("warnings")):
        gaps.append(_gap_row("option_trade_risk_warning", None, None, str(warning)))
    return gaps


def _essential_missing(option_candidate: dict, underlying_candidate: dict | None) -> list[str]:
    missing: list[str] = []
    underlying_ticker = _underlying_ticker(option_candidate, underlying_candidate)
    contract = _option_contract(option_candidate, underlying_ticker)
    bid = _safe_float(option_candidate.get("bid"))
    ask = _safe_float(option_candidate.get("ask"))
    mid = _mid(option_candidate)
    underlying_price = _underlying_price(option_candidate, underlying_candidate)

    if not underlying_ticker:
        missing.append("underlying_ticker")
    if not contract:
        missing.append("option_contract")
    if str(option_candidate.get("option_type") or "").lower() not in {"call", "put"}:
        missing.append("option_type")
    if _safe_float(option_candidate.get("strike")) is None:
        missing.append("strike")
    if not option_candidate.get("expiration"):
        missing.append("expiration")
    if _safe_int(option_candidate.get("days_to_expiration")) is None:
        missing.append("days_to_expiration")
    if bid is None or bid < 0:
        missing.append("bid")
    if ask is None or ask <= 0:
        missing.append("ask")
    if mid is None or mid <= 0:
        missing.append("mid")
    if bid is not None and ask is not None and ask < bid:
        missing.append("ask_greater_than_or_equal_to_bid")
    if underlying_price is None or underlying_price <= 0:
        missing.append("underlying_price")
    return missing


def _underlying_quality(option_candidate: dict, underlying_candidate: dict | None) -> tuple[float | None, list[str], list[str]]:
    score = _safe_float(_underlying_field(option_candidate, underlying_candidate, "opportunity_score"))
    if score is None:
        score = _safe_float(_underlying_field(option_candidate, underlying_candidate, "idea_score"))
    engine = _safe_float(_underlying_field(option_candidate, underlying_candidate, "score"))
    risk_reward = _safe_float(_underlying_field(option_candidate, underlying_candidate, "risk_reward"))
    data_confidence = _safe_float(_underlying_field(option_candidate, underlying_candidate, "data_confidence"))

    parts = [value for value in (score, engine, _score_minimum(risk_reward, 2.0), data_confidence) if value is not None]
    evidence: list[str] = []
    risks: list[str] = []
    if score is not None:
        evidence.append(f"Underlying opportunity score is {round(score, 2)}.")
    if engine is not None:
        evidence.append(f"Underlying engine score is {round(engine, 2)}.")
    if risk_reward is not None and risk_reward >= 2:
        evidence.append("Underlying risk/reward is at or above 2.0.")
    elif risk_reward is not None:
        risks.append("Underlying risk/reward is below 2.0.")
    return (sum(parts) / len(parts) if parts else None), evidence, risks


def _liquidity(option_candidate: dict, cfg: dict) -> tuple[float | None, list[str], list[str]]:
    volume = _safe_float(option_candidate.get("volume"))
    open_interest = _safe_float(option_candidate.get("open_interest"))
    minimum_volume = _safe_float(cfg.get("minimum_volume")) or DEFAULT_OPTION_CONSTRAINTS["minimum_volume"]
    minimum_open_interest = _safe_float(cfg.get("minimum_open_interest")) or DEFAULT_OPTION_CONSTRAINTS["minimum_open_interest"]
    parts = [
        _score_minimum(volume, minimum_volume * 3.0),
        _score_minimum(open_interest, minimum_open_interest * 2.0),
    ]
    parts = [part for part in parts if part is not None]
    evidence: list[str] = []
    risks: list[str] = []
    if volume is None:
        risks.append("Option volume is unavailable.")
    elif volume >= minimum_volume:
        evidence.append("Option volume meets the configured minimum.")
    else:
        risks.append("Option volume is below the configured minimum.")
    if open_interest is None:
        risks.append("Open interest is unavailable.")
    elif open_interest >= minimum_open_interest:
        evidence.append("Open interest meets the configured minimum.")
    else:
        risks.append("Open interest is below the configured minimum.")
    return (sum(parts) / len(parts) if parts else None), evidence, risks


def _spread_and_fill(option_candidate: dict, cfg: dict) -> tuple[float | None, list[str], list[str]]:
    bid = _safe_float(option_candidate.get("bid"))
    ask = _safe_float(option_candidate.get("ask"))
    mid = _mid(option_candidate)
    spread = _safe_float(option_candidate.get("spread_percent"))
    if spread is None and bid is not None and ask is not None and mid not in (None, 0) and ask >= bid:
        spread = (ask - bid) / mid
    max_spread = _safe_float(cfg.get("maximum_bid_ask_spread_percent")) or DEFAULT_OPTION_CONSTRAINTS["maximum_bid_ask_spread_percent"]
    fill_quality = str(
        option_candidate.get("fill_quality")
        or _as_dict(option_candidate.get("option_trade_risk")).get("fill_quality")
        or _as_dict(option_candidate.get("risk")).get("fill_quality")
        or ""
    ).lower()
    fill_score = {"good": 100.0, "usable": 80.0, "acceptable": 70.0, "poor": 35.0, "unavailable": 0.0}.get(fill_quality)
    spread_score = _score_maximum(spread, max_spread)
    parts = [part for part in (spread_score, fill_score) if part is not None]
    evidence: list[str] = []
    risks: list[str] = []
    if spread is not None and spread <= max_spread:
        evidence.append("Bid/ask spread is within the configured maximum.")
    elif spread is not None:
        risks.append("Bid/ask spread is wider than the configured maximum.")
    else:
        risks.append("Bid/ask spread is unavailable.")
    if fill_quality in {"good", "usable", "acceptable"}:
        evidence.append(f"Fill quality is {fill_quality}.")
    elif fill_quality:
        risks.append(f"Fill quality is {fill_quality}.")
    return (sum(parts) / len(parts) if parts else None), evidence, risks


def _expiration_fit(option_candidate: dict, cfg: dict) -> tuple[float | None, list[str], list[str]]:
    dte = _safe_float(option_candidate.get("days_to_expiration"))
    minimum = _safe_float(cfg.get("min_dte") or cfg.get("minimum_days_to_expiration")) or DEFAULT_OPTION_CONSTRAINTS["minimum_days_to_expiration"]
    maximum = _safe_float(cfg.get("max_dte") or cfg.get("maximum_days_to_expiration")) or DEFAULT_OPTION_CONSTRAINTS["maximum_days_to_expiration"]
    if dte is None or maximum <= minimum:
        return None, [], ["Days to expiration is unavailable."]
    midpoint = (minimum + maximum) / 2.0
    half_range = max((maximum - minimum) / 2.0, 1.0)
    if minimum <= dte <= maximum:
        score = 100.0 - min(40.0, abs(dte - midpoint) / half_range * 40.0)
        return score, ["DTE is inside the requested research window."], []
    if dte < minimum:
        return _score_minimum(dte, minimum), [], ["DTE is below the requested research window."]
    return _score_maximum(dte, maximum), [], ["DTE is above the requested research window."]


def _breakeven_realism(option_candidate: dict, underlying_candidate: dict | None) -> tuple[float | None, list[str], list[str]]:
    target_reaches = option_candidate.get("target_reaches_breakeven")
    if target_reaches is True:
        return 100.0, ["Underlying target reaches option breakeven."], []
    if target_reaches is False:
        return 20.0, [], ["Underlying target does not reach option breakeven."]

    breakeven_move = _safe_float(option_candidate.get("breakeven_move_percent"))
    if breakeven_move is not None:
        score = _clamp(100.0 - abs(breakeven_move) * 500.0)
        if score >= 70:
            return score, ["Breakeven move is within a realistic swing range."], []
        return score, [], ["Breakeven move is demanding relative to the underlying price."]

    breakeven = _safe_float(option_candidate.get("breakeven_price"))
    target = _safe_float(_underlying_field(option_candidate, underlying_candidate, "target_price"))
    option_type = str(option_candidate.get("option_type") or "").lower()
    if breakeven is not None and target is not None:
        if (option_type == "call" and target >= breakeven) or (option_type == "put" and target <= breakeven):
            return 100.0, ["Underlying target reaches option breakeven."], []
        return 25.0, [], ["Underlying target does not reach option breakeven."]
    return None, [], ["Breakeven context is unavailable."]


def _risk_reward(option_candidate: dict, cfg: dict) -> tuple[float | None, list[str], list[str]]:
    rr = _safe_float(option_candidate.get("risk_reward"))
    if rr is None:
        rr = _safe_float(_as_dict(option_candidate.get("evaluation")).get("risk_reward", {}).get("reward_risk"))
    minimum = _safe_float(cfg.get("minimum_risk_reward")) or DEFAULT_OPTION_CONSTRAINTS["minimum_risk_reward"]
    score = _score_minimum(rr, minimum * 2.0)
    if score is None:
        return None, [], ["Option risk/reward is unavailable."]
    if rr is not None and rr >= minimum:
        return score, ["Option risk/reward meets the configured minimum."], []
    return score, [], ["Option risk/reward is below the configured minimum."]


def _volatility_context(option_candidate: dict, cfg: dict) -> tuple[float | None, list[str], list[str]]:
    iv_rank = _safe_float(option_candidate.get("iv_rank"))
    iv_percentile = _safe_float(option_candidate.get("iv_percentile"))
    iv = _safe_float(option_candidate.get("implied_volatility") or option_candidate.get("iv"))
    iv_context = _as_dict(option_candidate.get("iv_context"))
    label = str(iv_context.get("iv_context") or option_candidate.get("mispricing_label") or "").lower()
    max_iv_rank = _safe_float(cfg.get("maximum_iv_rank")) or DEFAULT_OPTION_CONSTRAINTS["maximum_iv_rank"]
    evidence: list[str] = []
    risks: list[str] = []
    if iv_rank is not None:
        score = _score_maximum(iv_rank, max_iv_rank)
        if iv_rank <= max_iv_rank:
            evidence.append("IV rank is within the configured maximum.")
        else:
            risks.append("IV rank is above the configured maximum.")
        return score, evidence, risks
    if iv_percentile is not None:
        score = _score_maximum(iv_percentile, max_iv_rank)
        if iv_percentile <= max_iv_rank:
            evidence.append("IV percentile is within the configured maximum.")
        else:
            risks.append("IV percentile is above the configured maximum.")
        return score, evidence, risks
    if label in {"cheap", "normal", "undervalued"}:
        return 80.0, [f"Volatility context is {label}."], []
    if label in {"elevated", "expensive", "overvalued"}:
        return 35.0, [], [f"Volatility context is {label}."]
    if iv is not None:
        return 55.0, ["Implied volatility is available."], []
    return None, [], ["Implied volatility/IV rank is unavailable."]


def _greeks_quality(option_candidate: dict) -> tuple[float | None, list[str], list[str]]:
    greeks = _as_dict(option_candidate.get("greeks_monitoring") or option_candidate.get("greeks"))
    quality = str(greeks.get("greeks_quality") or option_candidate.get("greeks_quality") or "").lower()
    delta = _safe_float(option_candidate.get("delta") if option_candidate.get("delta") is not None else greeks.get("delta"))
    gamma = _safe_float(option_candidate.get("gamma") if option_candidate.get("gamma") is not None else greeks.get("gamma"))
    theta = _safe_float(option_candidate.get("theta") if option_candidate.get("theta") is not None else greeks.get("theta"))
    vega = _safe_float(option_candidate.get("vega") if option_candidate.get("vega") is not None else greeks.get("vega"))
    if quality:
        score = {"good": 100.0, "usable": 78.0, "poor": 25.0, "unavailable": 0.0}.get(quality, 45.0)
        if quality in {"good", "usable"}:
            return score, [f"Greeks quality is {quality}."], []
        return score, [], [f"Greeks quality is {quality}."]
    present = [value for value in (delta, gamma, theta, vega) if value is not None]
    if delta is not None and len(present) >= 3:
        return 80.0, ["Delta and most secondary Greeks are available."], []
    if delta is not None:
        return 45.0, ["Delta is available."], ["Secondary Greeks are incomplete."]
    return None, [], ["Usable Greeks are unavailable."]


def _data_confidence(rankable: bool, missing: list[str], components: dict) -> float:
    if not rankable:
        return 0.0
    available = sum(1 for component in components.values() if component.get("available"))
    base = 35.0 + (available / max(len(components), 1)) * 65.0
    optional_penalty = 0.0
    for item in missing:
        if item in {"implied_volatility", "iv_rank", "greeks", "volume", "open_interest"}:
            optional_penalty += 8.0
    return _clamp(base - optional_penalty)


def score_option_opportunity(
    option_candidate: dict,
    underlying_candidate: dict | None = None,
    config: dict | None = None,
) -> dict:
    weights = _normalize_weights(config)
    components = _empty_components(weights)
    candidate = option_candidate if isinstance(option_candidate, dict) else {}
    missing_requirements = _essential_missing(candidate, underlying_candidate)
    actionability_status = _actionability_status(candidate)

    if missing_requirements:
        return {
            "rankable": False,
            "opportunity_score": None,
            "score_version": OPTION_OPPORTUNITY_SCORE_VERSION,
            "actionability_status": actionability_status,
            "components": components,
            "data_confidence": 0.0,
            "why_ranked": [],
            "key_risks": _unique_texts([f"Missing essential option data: {', '.join(missing_requirements)}."]),
            "missing_requirements": missing_requirements,
            "qualification_gaps": [_gap_row(item, None, "required", f"{item} is required for exact option ranking.") for item in missing_requirements],
        }

    cfg = deepcopy(DEFAULT_OPTION_CONSTRAINTS)
    cfg.update(_as_dict(config))
    cfg.update(_as_dict(_as_dict(config).get("option_constraints")))
    option_preferences = _as_dict(_as_dict(config).get("option_preferences"))
    cfg.update({key: value for key, value in option_preferences.items() if key in {"min_dte", "max_dte"}})

    component_builders = {
        "underlying_quality": _underlying_quality(candidate, underlying_candidate),
        "contract_liquidity": _liquidity(candidate, cfg),
        "spread_and_fill": _spread_and_fill(candidate, cfg),
        "expiration_fit": _expiration_fit(candidate, cfg),
        "breakeven_realism": _breakeven_realism(candidate, underlying_candidate),
        "risk_reward": _risk_reward(candidate, cfg),
        "volatility_context": _volatility_context(candidate, cfg),
        "greeks_quality": _greeks_quality(candidate),
    }

    why_ranked: list[str] = []
    key_risks: list[str] = []
    optional_missing: list[str] = []
    for name, (score, evidence, risks) in component_builders.items():
        available = score is not None
        components[name] = _component(score=score, weight=weights[name], available=available, evidence=evidence)
        if evidence and available and _clamp(score) >= 60:
            why_ranked.extend(evidence)
        key_risks.extend(risks)
        if not available:
            if name == "contract_liquidity":
                optional_missing.extend(["volume", "open_interest"])
            elif name == "volatility_context":
                optional_missing.extend(["implied_volatility", "iv_rank"])
            elif name == "greeks_quality":
                optional_missing.append("greeks")
            else:
                optional_missing.append(name)

    weighted_score = 0.0
    for name, component in components.items():
        weighted_score += float(component["score"]) * weights[name]
    qualification_gaps = _constraint_gaps(candidate)
    missing_requirements = _unique_texts(missing_requirements + optional_missing + _as_list(candidate.get("missing_requirements")))
    key_risks.extend(candidate.get("key_risks") if isinstance(candidate.get("key_risks"), list) else [])
    _extend_texts(key_risks, candidate.get("rejection_reason"))
    _extend_texts(key_risks, _as_dict(candidate.get("option_trade_risk")).get("errors"))
    _extend_texts(key_risks, _as_dict(candidate.get("option_trade_risk")).get("warnings"))

    return {
        "rankable": True,
        "opportunity_score": _clamp(weighted_score),
        "score_version": OPTION_OPPORTUNITY_SCORE_VERSION,
        "actionability_status": actionability_status,
        "components": components,
        "data_confidence": _data_confidence(True, missing_requirements, components),
        "why_ranked": _unique_texts(why_ranked)[:8],
        "key_risks": _unique_texts(key_risks)[:10],
        "missing_requirements": missing_requirements,
        "qualification_gaps": qualification_gaps,
    }
