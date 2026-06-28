from __future__ import annotations

from copy import deepcopy
from typing import Any
import math

from ideas.opportunity_ranker import DEFAULT_STOCK_OPPORTUNITY_WEIGHTS
from scanner.scan_profiles import get_default_scan_profiles
from scanner.universe_builder import validate_ticker_universe

from .scan_plan import ScanPlan, SCAN_PLAN_VERSION, plan_to_dict


POLICY_VERSION = "scan_policy_v1"

SUPPORTED_UNIVERSES = ("mega_cap", "large_cap", "active", "tech", "growth", "sp500_sample", "custom")
SAFE_DEFAULT_UNIVERSES = ["large_cap"]
SUPPORTED_OBJECTIVES = {"best_ideas", "ticker_review", "watchlist", "options_research"}
SUPPORTED_INSTRUMENTS = {"stocks", "options", "both"}
SUPPORTED_DIRECTIONS = {"long", "short", "both"}
SUPPORTED_TIME_HORIZONS = {"swing"}
SUPPORTED_PROFILES = tuple(sorted(get_default_scan_profiles().keys()))

OPPORTUNITY_COMPONENT_KEYS = tuple(DEFAULT_STOCK_OPPORTUNITY_WEIGHTS.keys())

POLICY_LIMITS = {
    "max_tickers": {"min": 1, "max": 500, "default": 100},
    "max_candidates": {"min": 1, "max": 100, "default": 20},
    "max_final_trades": {"min": 0, "max": 10, "default": 5},
    "min_final_trades": {"min": 0, "max": 10, "default": 0},
    "option_min_dte": {"min": 7, "max": 90, "default": 14},
    "option_max_dte": {"min": 7, "max": 180, "default": 56},
    "max_contracts_per_ticker": {"min": 1, "max": 10, "default": 3},
    "max_option_premium": {"min": 1, "max": 10000, "default": None},
    "max_refinement_passes": {"min": 1, "max": 3, "default": 1},
    "minimum_relative_volume": {"min": 0.8, "max": 3.0, "default": None},
    "minimum_opportunity_score": {"min": 0.0, "max": 100.0, "default": None},
    "breakout_proximity_percent": {"min": 0.001, "max": 0.10, "default": None},
    "pullback_distance_percent": {"min": 0.001, "max": 0.15, "default": None},
    "min_stock_price": {"min": 0.01, "max": 10000, "default": None},
    "max_stock_price": {"min": 0.01, "max": 10000, "default": None},
}

IMMUTABLE_RULES = [
    "Paper trading only.",
    "Brokerage execution disabled.",
    "No order placement.",
    "Deterministic engine remains source of truth.",
    "Data freshness cannot be disabled.",
    "Essential market-data requirements cannot be disabled.",
    "Strict stock constraints cannot be bypassed.",
    "Portfolio and concentration blocks cannot be overridden.",
    "Circuit-breaker and macro hard blocks cannot be overridden.",
    "Blocked/watchlist candidates cannot be promoted.",
    "Option chain and quote requirements cannot be bypassed.",
    "Option bid/ask, liquidity, IV, Greeks, DTE, spread, breakeven, fill-quality, and risk checks cannot be bypassed.",
    "Logging eligibility cannot be changed by a ScanPlan.",
]

UNSUPPORTED_SAFETY_FIELDS = {
    "brokerage_execution_enabled",
    "paper_trading_only",
    "disable_data_quality",
    "disable_data_freshness",
    "disable_market_data",
    "bypass_constraints",
    "allow_unquoted_options",
    "auto_log_blocked",
    "place_orders",
    "order_execution_enabled",
}


def _adjustment(field: str, proposed: Any, approved: Any, reason: str) -> dict:
    return {
        "field": field,
        "proposed": _json_safe(proposed),
        "approved": _json_safe(approved),
        "reason": reason,
    }


def _json_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _json_safe(nested) for key, nested in value.items()}
    if isinstance(value, list):
        return [_json_safe(item) for item in value]
    if isinstance(value, tuple):
        return [_json_safe(item) for item in value]
    if isinstance(value, float) and not math.isfinite(value):
        if math.isnan(value):
            return "NaN"
        return "Infinity" if value > 0 else "-Infinity"
    return value


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
    return numeric if math.isfinite(numeric) else None


def _dedupe_preserve_order(values: list[Any]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        normalized = str(value or "").strip().lower()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        result.append(normalized)
    return result


def _normalize_enum(plan: dict, key: str, allowed: set[str], default: str, adjustments: list[dict]) -> str:
    proposed = str(plan.get(key) or default).strip().lower()
    if proposed not in allowed:
        adjustments.append(_adjustment(key, plan.get(key), default, f"Unsupported {key}; using safe default."))
        return default
    return proposed


def _clamp_number(
    plan: dict,
    key: str,
    limits_key: str,
    adjustments: list[dict],
    *,
    integer: bool = True,
    approved_value: Any | None = None,
) -> int | float | None:
    limits = POLICY_LIMITS[limits_key]
    proposed = plan.get(key) if approved_value is None else approved_value
    if proposed is None and limits.get("default") is None:
        return None
    numeric = _safe_float(proposed)
    if numeric is None:
        approved = limits["default"]
        adjustments.append(_adjustment(key, proposed, approved, "Malformed numeric value rejected; using safe default."))
        return approved
    clamped = max(limits["min"], min(limits["max"], numeric))
    if integer:
        clamped = int(clamped)
    else:
        clamped = round(float(clamped), 6)
    if clamped != numeric:
        adjustments.append(_adjustment(key, proposed, clamped, f"Value clamped to approved range {limits['min']}–{limits['max']}."))
    return clamped


def _normalize_universes(plan: dict, custom_tickers: list[str], adjustments: list[dict]) -> list[str]:
    proposed = _as_list(plan.get("universes")) or SAFE_DEFAULT_UNIVERSES
    valid: list[str] = []
    invalid: list[str] = []
    for universe in _dedupe_preserve_order(proposed):
        if universe not in SUPPORTED_UNIVERSES:
            invalid.append(universe)
            continue
        if universe == "custom" and not custom_tickers:
            invalid.append(universe)
            continue
        valid.append(universe)
    if invalid:
        adjustments.append(_adjustment("universes", proposed, valid or SAFE_DEFAULT_UNIVERSES, f"Removed unsupported or unusable universes: {', '.join(invalid)}."))
    if not valid:
        valid = SAFE_DEFAULT_UNIVERSES.copy()
        adjustments.append(_adjustment("universes", proposed, valid, "No valid universe remained; using safe default."))
    return valid


def _normalize_custom_tickers(plan: dict, max_tickers: int, adjustments: list[dict]) -> list[str]:
    proposed = _as_list(plan.get("custom_tickers"))
    validation = validate_ticker_universe(proposed, max_tickers=max_tickers)
    normalized = validation.get("tickers", []) if isinstance(validation, dict) else []
    if proposed != normalized or (isinstance(validation, dict) and validation.get("errors")):
        adjustments.append(
            _adjustment(
                "custom_tickers",
                proposed,
                normalized,
                "; ".join(validation.get("errors", [])) if isinstance(validation, dict) else "Custom ticker list normalized.",
            )
        )
    return normalized


def _normalize_profiles(plan: dict, adjustments: list[dict]) -> list[str]:
    proposed = _as_list(plan.get("profiles"))
    if not proposed:
        defaults = list(SUPPORTED_PROFILES)
        adjustments.append(_adjustment("profiles", proposed, defaults, "No profiles provided; using all supported default profiles."))
        return defaults
    valid: list[str] = []
    invalid: list[str] = []
    for profile in _dedupe_preserve_order(proposed):
        if profile in SUPPORTED_PROFILES:
            valid.append(profile)
        else:
            invalid.append(profile)
    if invalid:
        adjustments.append(_adjustment("profiles", proposed, valid or list(SUPPORTED_PROFILES), f"Removed unsupported profiles: {', '.join(invalid)}."))
    if not valid:
        valid = list(SUPPORTED_PROFILES)
        adjustments.append(_adjustment("profiles", proposed, valid, "No valid profiles remained; using all supported default profiles."))
    return valid


def _default_profile_weights() -> dict[str, float]:
    weight = 1.0 / len(SUPPORTED_PROFILES)
    return {profile: round(weight, 10) for profile in SUPPORTED_PROFILES}


def _normalize_weights(
    raw_weights: Any,
    allowed_keys: tuple[str, ...],
    default_weights: dict[str, float],
    field: str,
    adjustments: list[dict],
) -> dict[str, float]:
    if not isinstance(raw_weights, dict) or not raw_weights:
        return deepcopy(default_weights)
    valid: dict[str, float] = {}
    removed: dict[str, Any] = {}
    for key, value in raw_weights.items():
        normalized_key = str(key or "").strip()
        numeric = _safe_float(value)
        if normalized_key not in allowed_keys or numeric is None or numeric < 0:
            removed[normalized_key] = value
            continue
        valid[normalized_key] = numeric
    if removed:
        adjustments.append(_adjustment(field, raw_weights, valid, f"Removed unknown or invalid {field} entries."))
    total = sum(valid.values())
    if not valid or total <= 0:
        adjustments.append(_adjustment(field, raw_weights, default_weights, f"No usable {field} remained; using defaults."))
        return deepcopy(default_weights)
    normalized = {key: round(value / total, 10) for key, value in valid.items()}
    if normalized != raw_weights:
        adjustments.append(_adjustment(field, raw_weights, normalized, f"Normalized {field} to sum to 1."))
    return normalized


def _normalize_soft_adjustments(plan: dict, adjustments: list[dict]) -> tuple[dict, dict, dict]:
    soft = _as_dict(plan.get("soft_adjustments"))
    profile_weights = _normalize_weights(
        soft.get("profile_weights"),
        SUPPORTED_PROFILES,
        _default_profile_weights(),
        "soft_adjustments.profile_weights",
        adjustments,
    )
    opportunity_weights = _normalize_weights(
        soft.get("opportunity_weights"),
        OPPORTUNITY_COMPONENT_KEYS,
        deepcopy(DEFAULT_STOCK_OPPORTUNITY_WEIGHTS),
        "soft_adjustments.opportunity_weights",
        adjustments,
    )
    soft_preferences = {}
    for field, limits_key in (
        ("minimum_relative_volume", "minimum_relative_volume"),
        ("minimum_opportunity_score", "minimum_opportunity_score"),
        ("breakout_proximity_percent", "breakout_proximity_percent"),
        ("pullback_distance_percent", "pullback_distance_percent"),
        ("min_stock_price", "min_stock_price"),
        ("max_stock_price", "max_stock_price"),
    ):
        value = soft.get(field)
        if value is None:
            soft_preferences[field] = None
            continue
        soft_preferences[field] = _clamp_number(soft, field, limits_key, adjustments, integer=False)
    min_price = soft_preferences.get("min_stock_price")
    max_price = soft_preferences.get("max_stock_price")
    if min_price is not None and max_price is not None and max_price < min_price:
        adjustments.append(_adjustment("soft_adjustments.max_stock_price", max_price, min_price, "max_stock_price cannot be below min_stock_price."))
        soft_preferences["max_stock_price"] = min_price
    return profile_weights, opportunity_weights, soft_preferences


def _normalize_allowed_strategy_types(value: Any) -> list[str]:
    return [str(item).strip().lower() for item in _as_list(value) if str(item).strip()]


def _runtime_bool(context: dict, *keys: str, default: bool = False) -> bool:
    for key in keys:
        if key in context and isinstance(context[key], bool):
            return context[key]
    return default


def _runtime_options_ready(context: dict) -> bool:
    return _runtime_bool(context, "safe_to_run_options", "options_ready", "option_quotes_validated", default=False)


def _runtime_market_data_ready(context: dict) -> bool:
    if "market_data_available" in context and isinstance(context["market_data_available"], bool):
        return context["market_data_available"]
    provider_status = str(context.get("provider_status") or context.get("market_data_provider_status") or "").lower()
    if provider_status in {"unavailable", "offline", "failed"}:
        return False
    return _runtime_bool(context, "safe_to_run_market_data", "market_data_ready", default=True)


def _parse_plan(proposed_plan: ScanPlan | dict, errors: list[str]) -> tuple[dict, dict]:
    original = proposed_plan.model_dump(mode="python") if isinstance(proposed_plan, ScanPlan) else deepcopy(proposed_plan if isinstance(proposed_plan, dict) else {})
    try:
        parsed = plan_to_dict(proposed_plan)
    except Exception as exc:
        errors.append(f"ScanPlan parsing failed; defaults were used where needed: {exc}")
        base = ScanPlan().model_dump(mode="json")
        if isinstance(original, dict):
            base.update(original)
        parsed = base
    return _json_safe(original), parsed


def validate_scan_plan(
    proposed_plan: ScanPlan | dict,
    runtime_context: dict | None = None,
) -> dict:
    adjustments: list[dict] = []
    warnings: list[str] = []
    errors: list[str] = []
    context = _as_dict(runtime_context)
    proposed_serialized, plan = _parse_plan(proposed_plan, errors)

    for field in sorted(UNSUPPORTED_SAFETY_FIELDS.intersection(proposed_serialized.keys())):
        adjustments.append(_adjustment(field, proposed_serialized.get(field), "ignored", "Unsupported safety override ignored by policy."))
        warnings.append(f"Ignored unsupported safety override: {field}.")

    requested_instrument = _normalize_enum(plan, "requested_instrument", SUPPORTED_INSTRUMENTS, "stocks", adjustments)
    objective = _normalize_enum(plan, "objective", SUPPORTED_OBJECTIVES, "best_ideas", adjustments)
    time_horizon = _normalize_enum(plan, "time_horizon", SUPPORTED_TIME_HORIZONS, "swing", adjustments)
    direction = _normalize_enum(plan, "direction", SUPPORTED_DIRECTIONS, "long", adjustments)

    max_tickers = _clamp_number(plan, "max_tickers", "max_tickers", adjustments)
    max_candidates = _clamp_number(plan, "max_candidates", "max_candidates", adjustments)
    max_final_trades = _clamp_number(plan, "max_final_trades", "max_final_trades", adjustments)
    min_final_trades = _clamp_number(plan, "min_final_trades", "min_final_trades", adjustments)
    if min_final_trades is not None and max_final_trades is not None and min_final_trades > max_final_trades:
        adjustments.append(_adjustment("min_final_trades", min_final_trades, max_final_trades, "min_final_trades cannot exceed max_final_trades."))
        min_final_trades = max_final_trades

    custom_tickers = _normalize_custom_tickers(plan, int(max_tickers or 100), adjustments)
    universes = _normalize_universes(plan, custom_tickers, adjustments)
    profiles = _normalize_profiles(plan, adjustments)

    include_options = bool(plan.get("include_options"))
    prefer_options = bool(plan.get("prefer_options"))
    if requested_instrument == "stocks":
        if include_options is not False:
            adjustments.append(_adjustment("include_options", include_options, False, "Stock-only request cannot include options."))
        if prefer_options is not False:
            adjustments.append(_adjustment("prefer_options", prefer_options, False, "Stock-only request cannot prefer options."))
        include_options = False
        prefer_options = False
    elif requested_instrument == "options":
        if include_options is not True:
            adjustments.append(_adjustment("include_options", include_options, True, "Options request requires options research to be enabled."))
        include_options = True
    elif requested_instrument == "both":
        include_options = bool(include_options)

    if prefer_options and not include_options:
        adjustments.append(_adjustment("prefer_options", prefer_options, False, "prefer_options cannot be true when include_options is false."))
        prefer_options = False

    option_preferences = _as_dict(plan.get("option_preferences"))
    option_min_dte = _clamp_number(option_preferences, "min_dte", "option_min_dte", adjustments)
    option_max_dte = _clamp_number(option_preferences, "max_dte", "option_max_dte", adjustments)
    if option_max_dte is not None and option_min_dte is not None and option_max_dte < option_min_dte:
        adjustments.append(_adjustment("option_preferences.max_dte", option_max_dte, option_min_dte, "max_dte cannot be below min_dte."))
        option_max_dte = option_min_dte
    max_contracts = _clamp_number(option_preferences, "max_contracts_per_ticker", "max_contracts_per_ticker", adjustments)
    max_option_premium = None
    if option_preferences.get("max_option_premium") is not None:
        max_option_premium = _clamp_number(option_preferences, "max_option_premium", "max_option_premium", adjustments, integer=False)
    allowed_strategy_types = _normalize_allowed_strategy_types(option_preferences.get("allowed_strategy_types"))

    refinement = _as_dict(plan.get("refinement"))
    max_refinement_passes = _clamp_number(refinement, "max_passes", "max_refinement_passes", adjustments)

    profile_weights, opportunity_weights, soft_preferences = _normalize_soft_adjustments(plan, adjustments)

    options_ready = _runtime_options_ready(context)
    options_final_eligibility = bool(include_options and options_ready)
    if include_options and not options_ready:
        warnings.append("Options research may remain requested, but final option recommendations remain blocked until options runtime readiness and deterministic option gates pass.")

    market_data_ready = _runtime_market_data_ready(context)
    if not market_data_ready:
        warnings.append("Market-data provider readiness failed; preserve this plan for audit but do not loosen gates or invent candidates.")

    approved_plan = {
        "plan_version": SCAN_PLAN_VERSION,
        "requested_instrument": requested_instrument,
        "objective": objective,
        "time_horizon": time_horizon,
        "direction": direction,
        "universes": universes,
        "custom_tickers": custom_tickers,
        "profiles": profiles,
        "max_tickers": max_tickers,
        "max_candidates": max_candidates,
        "max_final_trades": max_final_trades,
        "min_final_trades": min_final_trades,
        "include_market_regime": bool(plan.get("include_market_regime")),
        "include_relative_strength": bool(plan.get("include_relative_strength")),
        "include_catalysts": bool(plan.get("include_catalysts")),
        "include_portfolio_risk": bool(plan.get("include_portfolio_risk")),
        "include_position_sizing": bool(plan.get("include_position_sizing")),
        "include_options": include_options,
        "prefer_options": prefer_options,
        "option_preferences": {
            "min_dte": option_min_dte,
            "max_dte": option_max_dte,
            "max_contracts_per_ticker": max_contracts,
            "max_option_premium": max_option_premium,
            "allowed_strategy_types": allowed_strategy_types,
        },
        "research_preferences": _as_dict(plan.get("research_preferences")),
        "soft_adjustments": {
            "profile_weights": profile_weights,
            "opportunity_weights": opportunity_weights,
            **soft_preferences,
        },
        "refinement": {
            "max_passes": max_refinement_passes,
            "allow_broader_universe_on_retry": bool(refinement.get("allow_broader_universe_on_retry", True)),
            "allow_profile_change_on_retry": bool(refinement.get("allow_profile_change_on_retry", True)),
        },
        "reasoning_summary": str(plan.get("reasoning_summary") or ""),
        "created_by": str(plan.get("created_by") or "deterministic_default"),
        "request_id": plan.get("request_id"),
    }

    execution_config = {
        "universes": universes,
        "custom_tickers": custom_tickers,
        "profiles": profiles,
        "max_tickers": max_tickers,
        "max_candidates": max_candidates,
        "max_trades": max_final_trades,
        "min_trades": min_final_trades,
        "include_market_regime": approved_plan["include_market_regime"],
        "include_relative_strength": approved_plan["include_relative_strength"],
        "include_catalysts": approved_plan["include_catalysts"],
        "include_portfolio_risk": approved_plan["include_portfolio_risk"],
        "include_position_sizing": approved_plan["include_position_sizing"],
        "include_options": include_options,
        "prefer_options": prefer_options,
        "max_option_contracts_per_trade": max_contracts,
        "option_min_dte": option_min_dte,
        "option_max_dte": option_max_dte,
        "max_option_premium": max_option_premium,
        "profile_weights": profile_weights,
        "opportunity_weights": opportunity_weights,
        "soft_scanner_preferences": soft_preferences,
        "max_refinement_passes": max_refinement_passes,
        "paper_trading_only": True,
        "brokerage_execution_enabled": False,
        "options_final_eligibility": options_final_eligibility,
        "market_data_ready": market_data_ready,
        "provider_readiness_failure": not market_data_ready,
    }

    return {
        "ok": not errors,
        "policy_version": POLICY_VERSION,
        "proposed_plan": proposed_serialized,
        "approved_plan": _json_safe(approved_plan),
        "adjustments": adjustments,
        "warnings": list(dict.fromkeys(warnings)),
        "errors": errors,
        "immutable_rules": IMMUTABLE_RULES.copy(),
        "execution_config": _json_safe(execution_config),
    }
