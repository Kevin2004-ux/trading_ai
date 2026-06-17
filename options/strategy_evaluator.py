from __future__ import annotations

import math
from copy import deepcopy
from typing import Any

from options.options_risk import evaluate_option_trade_risk


RESEARCH_ONLY_STRATEGIES = {
    "covered_call_research",
    "cash_secured_put_research",
    "call_credit_spread_research",
    "put_credit_spread_research",
}


DEFAULT_STRATEGY_CONFIG = {
    "wide_leg_spread_research_threshold": 0.15,
    "wide_leg_spread_block_threshold": 0.25,
    "minimum_dte": 7,
    "minimum_debit_spread_reward_risk": 0.5,
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


def _merge_config(config: dict | None) -> dict:
    merged = deepcopy(DEFAULT_STRATEGY_CONFIG)
    if isinstance(config, dict):
        merged.update(config)
    return merged


def _legs(strategy: dict) -> list[dict]:
    return [leg for leg in strategy.get("legs", []) if isinstance(leg, dict)] if isinstance(strategy, dict) else []


def _leg_contract(leg: dict) -> dict:
    contract = leg.get("contract")
    return contract if isinstance(contract, dict) else leg


def _leg_action(leg: dict) -> str:
    return str(leg.get("action", "buy")).lower()


def _leg_spread_percent(contract: dict) -> float | None:
    spread = _safe_float(contract.get("spread_percent"))
    if spread is not None:
        return spread
    bid = _safe_float(contract.get("bid"))
    ask = _safe_float(contract.get("ask"))
    mid = _safe_float(contract.get("mid"))
    if mid is None and bid is not None and ask is not None:
        mid = (bid + ask) / 2.0
    if bid is None or ask is None or mid in (None, 0) or ask < bid:
        return None
    return (ask - bid) / mid


def _strategy_direction(strategy: dict) -> str:
    strategy_type = str(strategy.get("strategy_type", "")).lower()
    if strategy_type in {"long_call", "bull_call_debit_spread", "put_credit_spread_research", "cash_secured_put_research"}:
        return "bullish"
    if strategy_type in {"long_put", "bear_put_debit_spread", "call_credit_spread_research", "covered_call_research"}:
        return "bearish" if strategy_type != "covered_call_research" else "neutral"
    return str(strategy.get("direction", "neutral")).lower()


def _underlying_bias(underlying_view: dict | None) -> str:
    if not isinstance(underlying_view, dict):
        return "unknown"
    for key in ("option_bias", "bias", "direction", "view"):
        value = str(underlying_view.get(key, "")).lower()
        if value in {"bullish", "long", "up", "upside"}:
            return "bullish"
        if value in {"bearish", "short", "down", "downside"}:
            return "bearish"
        if value in {"neutral", "sideways"}:
            return "neutral"
    return "unknown"


def evaluate_strategy_liquidity(strategy: dict) -> dict:
    errors: list[str] = []
    warnings: list[str] = []
    leg_results = []
    max_spread = 0.0

    for leg in _legs(strategy):
        contract = _leg_contract(leg)
        bid = _safe_float(contract.get("bid"))
        ask = _safe_float(contract.get("ask"))
        mid = _safe_float(contract.get("mid"))
        if mid is None and bid is not None and ask is not None:
            mid = (bid + ask) / 2.0
        spread_percent = _leg_spread_percent(contract)
        if bid is None or ask is None or mid in (None, 0) or ask < bid:
            errors.append(f"{contract.get('option_contract') or contract.get('ticker') or 'leg'} is missing usable bid/ask quotes.")
            quality = "unavailable"
        elif spread_percent is None:
            errors.append(f"{contract.get('option_contract') or contract.get('ticker') or 'leg'} spread is unavailable.")
            quality = "unavailable"
        elif spread_percent > DEFAULT_STRATEGY_CONFIG["wide_leg_spread_block_threshold"]:
            errors.append(f"{contract.get('option_contract') or contract.get('ticker') or 'leg'} spread is too wide.")
            quality = "poor"
        elif spread_percent > DEFAULT_STRATEGY_CONFIG["wide_leg_spread_research_threshold"]:
            warnings.append(f"{contract.get('option_contract') or contract.get('ticker') or 'leg'} spread is wide.")
            quality = "poor"
        elif spread_percent > 0.08:
            quality = "usable"
        else:
            quality = "good"
        if spread_percent is not None:
            max_spread = max(max_spread, spread_percent)
        leg_results.append(
            {
                "option_contract": contract.get("option_contract") or contract.get("ticker"),
                "bid": bid,
                "ask": ask,
                "mid": mid,
                "spread_percent": spread_percent,
                "liquidity_quality": quality,
            }
        )

    if not leg_results:
        errors.append("Strategy has no option legs.")

    if errors:
        quality = "unavailable" if any("missing usable" in error for error in errors) else "poor"
    elif warnings:
        quality = "poor"
    elif max_spread <= 0.08:
        quality = "good"
    else:
        quality = "usable"

    return {
        "ok": not errors,
        "liquidity_quality": quality,
        "max_leg_spread_percent": round(max_spread, 4),
        "legs": leg_results,
        "warnings": warnings,
        "errors": errors,
    }


def evaluate_strategy_risk_reward(strategy: dict) -> dict:
    max_loss = _safe_float(strategy.get("max_loss"))
    max_profit = _safe_float(strategy.get("max_profit"))
    net_debit = _safe_float(strategy.get("net_debit"))
    net_credit = _safe_float(strategy.get("net_credit"))
    strategy_type = str(strategy.get("strategy_type", "")).lower()
    warnings: list[str] = []
    errors: list[str] = []

    reward_risk = None
    if max_loss not in (None, 0) and max_profit is not None:
        reward_risk = max_profit / max_loss
    if strategy_type in RESEARCH_ONLY_STRATEGIES and max_loss is not None:
        quality = "usable"
    elif max_loss is None or max_loss <= 0:
        quality = "unavailable"
        errors.append("Max loss must be known for strategy risk/reward evaluation.")
    elif max_profit is None:
        quality = "usable" if strategy_type in {"long_call", "long_put"} and net_debit else "unavailable"
        if quality == "unavailable":
            errors.append("Max profit is unavailable.")
    elif reward_risk is not None and reward_risk >= 1.0:
        quality = "good"
    elif reward_risk is not None and reward_risk >= DEFAULT_STRATEGY_CONFIG["minimum_debit_spread_reward_risk"]:
        quality = "usable"
    else:
        quality = "poor"
        warnings.append("Strategy reward/risk is weak.")

    return {
        "ok": not errors,
        "risk_reward_quality": quality,
        "max_loss": max_loss,
        "max_profit": max_profit,
        "net_debit": net_debit,
        "net_credit": net_credit,
        "reward_risk": round(reward_risk, 4) if reward_risk is not None else None,
        "warnings": warnings,
        "errors": errors,
    }


def evaluate_strategy_greeks(strategy: dict) -> dict:
    totals = {"delta": 0.0, "gamma": 0.0, "theta": 0.0, "vega": 0.0, "rho": 0.0}
    warnings: list[str] = []
    errors: list[str] = []
    leg_results = []

    for leg in _legs(strategy):
        contract = _leg_contract(leg)
        multiplier = 1.0 if _leg_action(leg) == "buy" else -1.0
        missing = [key for key in ("delta", "gamma", "theta", "vega") if _safe_float(contract.get(key)) is None]
        if missing:
            errors.append(f"{contract.get('option_contract') or contract.get('ticker') or 'leg'} missing Greeks: {', '.join(missing)}.")
        for key in totals:
            value = _safe_float(contract.get(key))
            if value is not None:
                totals[key] += value * multiplier
        leg_results.append(
            {
                "option_contract": contract.get("option_contract") or contract.get("ticker"),
                "action": _leg_action(leg),
                "missing_greeks": missing,
            }
        )

    if not leg_results:
        errors.append("Strategy has no option legs.")
    if errors:
        quality = "unavailable"
        risk_level = "blocked"
    elif abs(totals["gamma"]) > 0.25 or abs(totals["delta"]) > 1.0:
        quality = "usable"
        risk_level = "high"
        warnings.append("Strategy Greeks indicate elevated directional or gamma exposure.")
    elif abs(totals["gamma"]) > 0.12 or abs(totals["delta"]) > 0.7:
        quality = "usable"
        risk_level = "medium"
    else:
        quality = "good"
        risk_level = "low"

    return {
        "ok": not errors,
        "greeks_quality": quality,
        "risk_level": risk_level,
        "net_greeks": {key: round(value, 4) for key, value in totals.items()},
        "legs": leg_results,
        "warnings": warnings,
        "errors": errors,
    }


def evaluate_option_strategy(
    strategy: dict,
    underlying_view: dict | None = None,
    config: dict | None = None,
) -> dict:
    cfg = _merge_config(config)
    strategy_type = str((strategy or {}).get("strategy_type", "")).lower()
    warnings: list[str] = []
    errors: list[str] = []
    reasons: list[str] = []

    liquidity = evaluate_strategy_liquidity(strategy)
    risk_reward = evaluate_strategy_risk_reward(strategy)
    greeks = evaluate_strategy_greeks(strategy)
    warnings.extend(liquidity.get("warnings", []))
    warnings.extend(risk_reward.get("warnings", []))
    warnings.extend(greeks.get("warnings", []))
    errors.extend(liquidity.get("errors", []))
    errors.extend(risk_reward.get("errors", []))
    errors.extend(greeks.get("errors", []))

    dte = _safe_float(strategy.get("days_to_expiration"))
    if dte is None:
        errors.append("Days to expiration is required.")
    elif dte < cfg["minimum_dte"]:
        errors.append("DTE under 7 blocks option strategies.")

    leg_risks = []
    for leg in _legs(strategy):
        contract = _leg_contract(leg)
        risk_contract = deepcopy(contract)
        risk_contract["strategy"] = strategy_type
        risk_contract["direction"] = "short" if _leg_action(leg) == "sell" else "long"
        risk = evaluate_option_trade_risk(risk_contract, config=config)
        leg_risks.append({"option_contract": contract.get("option_contract") or contract.get("ticker"), "risk": risk})
        if not risk.get("ok"):
            errors.extend(str(item) for item in risk.get("errors", []) if item)
        warnings.extend(str(item) for item in risk.get("warnings", []) if item)
    iv_labels = {
        str((item.get("risk") or {}).get("iv_context", {}).get("iv_context", "")).lower()
        for item in leg_risks
        if isinstance(item.get("risk"), dict)
    }

    thesis = _underlying_bias(underlying_view)
    direction = _strategy_direction(strategy)
    if thesis == "unknown" or direction == "neutral":
        alignment = "neutral" if thesis != "unknown" else "unknown"
    elif thesis == direction:
        alignment = "aligned"
        reasons.append("Strategy direction aligns with the underlying thesis.")
    else:
        alignment = "conflict"
        errors.append("Strategy direction conflicts with the underlying thesis.")

    if strategy_type in {"long_call", "long_put"} and ("expensive" in iv_labels or "elevated" in iv_labels):
        warnings.append("Long premium strategy is penalized because IV is elevated or expensive.")
    if strategy_type in {"bull_call_debit_spread", "bear_put_debit_spread"} and "elevated" in iv_labels:
        reasons.append("Debit spread can reduce long-premium exposure when IV is elevated.")
    if strategy_type in RESEARCH_ONLY_STRATEGIES:
        warnings.append("Strategy remains research-only until account, position, margin, and assignment rules are implemented.")

    score = 50.0
    score += {"good": 18, "usable": 8, "poor": -12, "unavailable": -30}.get(liquidity["liquidity_quality"], 0)
    score += {"good": 14, "usable": 6, "poor": -10, "unavailable": -25}.get(risk_reward["risk_reward_quality"], 0)
    score += {"good": 14, "usable": 6, "poor": -10, "unavailable": -25}.get(greeks["greeks_quality"], 0)
    score += {"aligned": 12, "neutral": 0, "unknown": -4, "conflict": -30}.get(alignment, 0)
    if "elevated" in iv_labels and strategy_type in {"bull_call_debit_spread", "bear_put_debit_spread"}:
        score += 8
    if strategy_type in {"long_call", "long_put"} and ("elevated" in iv_labels or "expensive" in iv_labels):
        score -= 14
    if strategy_type in RESEARCH_ONLY_STRATEGIES:
        score -= 8
    score = round(max(0.0, min(score, 100.0)), 2)

    if errors:
        status = "blocked"
    elif strategy_type in RESEARCH_ONLY_STRATEGIES:
        status = "research_only"
    elif liquidity["liquidity_quality"] == "poor" or risk_reward["risk_reward_quality"] == "poor" or greeks["risk_level"] in {"medium", "high"}:
        status = "research_only"
    else:
        status = "paper_eligible"

    risk_level = "blocked" if status == "blocked" else greeks.get("risk_level", "medium")
    approved = status == "paper_eligible"
    return {
        "ok": status != "blocked",
        "strategy_type": strategy_type,
        "approved": approved,
        "status": status,
        "score": score,
        "risk_level": risk_level,
        "expected_move_alignment": alignment,
        "liquidity_quality": liquidity.get("liquidity_quality"),
        "risk_reward_quality": risk_reward.get("risk_reward_quality"),
        "greeks_quality": greeks.get("greeks_quality"),
        "liquidity": liquidity,
        "risk_reward": risk_reward,
        "greeks": greeks,
        "leg_risks": leg_risks,
        "reasons": reasons,
        "warnings": warnings,
        "errors": errors,
    }
