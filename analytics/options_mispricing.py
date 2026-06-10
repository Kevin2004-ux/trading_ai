from __future__ import annotations

import math
from typing import Any

import numpy as np

try:
    from scipy.stats import norm
except ImportError:  # pragma: no cover - depends on local environment
    norm = None


TRADING_DAYS_PER_YEAR = 252
DEFAULT_RISK_FREE_RATE = 0.05


def _safe_float(value: Any) -> float | None:
    try:
        if value is None:
            return None
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    if math.isnan(numeric) or math.isinf(numeric):
        return None
    return numeric


def _option_type(value: Any) -> str | None:
    normalized = str(value or "").strip().lower()
    if normalized in {"call", "put"}:
        return normalized
    if normalized in {"c", "calls"}:
        return "call"
    if normalized in {"p", "puts"}:
        return "put"
    return None


def _cdf(value: float) -> float:
    if norm is not None:
        return float(norm.cdf(value))
    return 0.5 * (1.0 + math.erf(value / math.sqrt(2.0)))


def _label_from_score(score: float, warnings: list[str], target_exceeds_breakeven: bool) -> str:
    lowered = {warning.lower() for warning in warnings}
    if "missing_critical_data" in lowered:
        return "mispricing_unknown"
    if "very_high_iv_vs_hv" in lowered or "extreme_spread" in lowered:
        return "high_iv_risky"
    if "low_probability_delta" in lowered:
        return "cheap_but_low_probability"
    if score >= 74:
        return "attractive_value"
    if score >= 50:
        return "fair_value"
    if score >= 35:
        return "overpriced"
    if "iv_above_hv" in lowered:
        return "high_iv_risky"
    return "overpriced"


def estimate_historical_volatility(
    bars: list[dict] | None = None,
    close_prices: list[float] | None = None,
    window: int = 20,
) -> dict:
    if close_prices is None and bars is None:
        return {
            "ok": False,
            "historical_volatility": None,
            "window": window,
            "sample_size": 0,
            "error": "bars or close_prices are required.",
        }

    closes: list[float] = []
    if isinstance(close_prices, list):
        closes.extend(value for value in (_safe_float(item) for item in close_prices) if value is not None and value > 0)
    elif isinstance(bars, list):
        for bar in bars:
            if not isinstance(bar, dict):
                continue
            close_value = _safe_float(bar.get("close"))
            if close_value is None:
                close_value = _safe_float(bar.get("Close"))
            if close_value is not None and close_value > 0:
                closes.append(close_value)

    if len(closes) < max(window, 2):
        return {
            "ok": False,
            "historical_volatility": None,
            "window": window,
            "sample_size": len(closes),
            "error": "Not enough price history to estimate historical volatility.",
        }

    recent_closes = np.array(closes[-window:], dtype=float)
    log_returns = np.diff(np.log(recent_closes))
    if len(log_returns) < 2:
        return {
            "ok": False,
            "historical_volatility": None,
            "window": window,
            "sample_size": len(recent_closes),
            "error": "Not enough returns to estimate historical volatility.",
        }

    hv = float(np.std(log_returns, ddof=1) * math.sqrt(TRADING_DAYS_PER_YEAR))
    return {
        "ok": True,
        "historical_volatility": hv,
        "window": window,
        "sample_size": len(recent_closes),
        "error": None,
    }


def black_scholes_value(
    option_type: str,
    underlying_price: float,
    strike: float,
    days_to_expiration: int,
    volatility: float,
    risk_free_rate: float = DEFAULT_RISK_FREE_RATE,
) -> dict:
    normalized_option_type = _option_type(option_type)
    S = _safe_float(underlying_price)
    K = _safe_float(strike)
    sigma = _safe_float(volatility)
    T_days = int(days_to_expiration) if days_to_expiration is not None else None
    r = _safe_float(risk_free_rate)

    if normalized_option_type is None:
        return {"ok": False, "theoretical_value": None, "inputs": None, "error": "option_type must be call or put."}
    if S is None or S <= 0:
        return {"ok": False, "theoretical_value": None, "inputs": None, "error": "underlying_price must be positive."}
    if K is None or K <= 0:
        return {"ok": False, "theoretical_value": None, "inputs": None, "error": "strike must be positive."}
    if sigma is None or sigma <= 0:
        return {"ok": False, "theoretical_value": None, "inputs": None, "error": "volatility must be positive."}
    if T_days is None or T_days <= 0:
        return {"ok": False, "theoretical_value": None, "inputs": None, "error": "days_to_expiration must be positive."}
    if r is None:
        r = DEFAULT_RISK_FREE_RATE

    T = T_days / 365.25
    d1 = (math.log(S / K) + (r + 0.5 * sigma * sigma) * T) / (sigma * math.sqrt(T))
    d2 = d1 - sigma * math.sqrt(T)

    if normalized_option_type == "call":
        value = S * _cdf(d1) - K * math.exp(-r * T) * _cdf(d2)
    else:
        value = K * math.exp(-r * T) * _cdf(-d2) - S * _cdf(-d1)

    return {
        "ok": True,
        "theoretical_value": float(max(value, 0.0)),
        "inputs": {
            "option_type": normalized_option_type,
            "underlying_price": S,
            "strike": K,
            "days_to_expiration": T_days,
            "volatility": sigma,
            "risk_free_rate": r,
        },
        "error": None,
    }


def calculate_expected_move_context(
    underlying_candidate: dict,
    option_candidate: dict,
) -> dict:
    current_price = _safe_float(underlying_candidate.get("current_price")) or _safe_float(underlying_candidate.get("entry_price"))
    target_price = _safe_float(underlying_candidate.get("target_price")) or _safe_float(option_candidate.get("underlying_target_price"))
    breakeven_price = _safe_float(option_candidate.get("breakeven_price"))
    breakeven_move_percent = _safe_float(option_candidate.get("breakeven_move_percent"))

    underlying_target_move_percent = None
    target_exceeds_breakeven = None
    target_vs_breakeven_margin = None

    option_type = _option_type(option_candidate.get("option_type"))
    if current_price not in (None, 0) and target_price is not None:
        if option_type == "put":
            underlying_target_move_percent = (current_price - target_price) / current_price
        else:
            underlying_target_move_percent = (target_price - current_price) / current_price

    if target_price is not None and breakeven_price is not None:
        if option_type == "put":
            target_exceeds_breakeven = target_price <= breakeven_price
            target_vs_breakeven_margin = breakeven_price - target_price
        else:
            target_exceeds_breakeven = target_price >= breakeven_price
            target_vs_breakeven_margin = target_price - breakeven_price

    return {
        "current_price": current_price,
        "underlying_target_price": target_price,
        "underlying_target_move_percent": underlying_target_move_percent,
        "breakeven_price": breakeven_price,
        "breakeven_move_percent": breakeven_move_percent,
        "target_exceeds_breakeven": target_exceeds_breakeven,
        "target_vs_breakeven_margin": target_vs_breakeven_margin,
    }


def evaluate_option_mispricing(
    option_candidate: dict,
    underlying_candidate: dict,
    historical_volatility: float | None = None,
    risk_free_rate: float = DEFAULT_RISK_FREE_RATE,
) -> dict:
    option_contract = str(option_candidate.get("option_contract") or option_candidate.get("ticker") or "")
    ticker = str(
        option_candidate.get("underlying_ticker")
        or underlying_candidate.get("ticker")
        or ""
    ).upper()

    option_type = _option_type(option_candidate.get("option_type"))
    market_mid = _safe_float(option_candidate.get("mid"))
    underlying_price = _safe_float(underlying_candidate.get("current_price")) or _safe_float(underlying_candidate.get("entry_price"))
    strike = _safe_float(option_candidate.get("strike"))
    dte = option_candidate.get("days_to_expiration")
    implied_volatility = _safe_float(option_candidate.get("implied_volatility"))
    delta = abs(_safe_float(option_candidate.get("delta")) or 0.0)
    volume = _safe_float(option_candidate.get("volume")) or 0.0
    open_interest = _safe_float(option_candidate.get("open_interest")) or 0.0
    spread_percent = _safe_float(option_candidate.get("spread_percent"))

    warnings: list[str] = []
    if option_type is None or market_mid is None or underlying_price is None or strike is None or dte is None or implied_volatility is None:
        warnings.append("missing_critical_data")
        return {
            "ok": False,
            "option_contract": option_contract,
            "ticker": ticker,
            "mispricing_label": "mispricing_unknown",
            "mispricing_score": 0.0,
            "market_mid": market_mid,
            "theoretical_value": None,
            "theoretical_edge_percent": None,
            "historical_volatility": historical_volatility,
            "implied_volatility": implied_volatility,
            "iv_vs_hv_ratio": None,
            "breakeven_price": _safe_float(option_candidate.get("breakeven_price")),
            "breakeven_move_percent": _safe_float(option_candidate.get("breakeven_move_percent")),
            "underlying_target_price": _safe_float(underlying_candidate.get("target_price")),
            "underlying_target_move_percent": None,
            "target_exceeds_breakeven": None,
            "liquidity_penalty": None,
            "spread_penalty": None,
            "probability_context": {},
            "warnings": warnings,
            "explanation": "Critical option inputs are missing, so mispricing cannot be estimated reliably.",
            "error": "Missing critical data for option mispricing evaluation.",
        }

    hv = _safe_float(historical_volatility)
    if hv is None:
        bars = underlying_candidate.get("bars")
        hv_result = estimate_historical_volatility(bars=bars if isinstance(bars, list) else None)
        if hv_result.get("ok"):
            hv = _safe_float(hv_result.get("historical_volatility"))
        else:
            warnings.append("historical_volatility_unavailable")

    volatility_for_model = hv or implied_volatility
    theoretical_result = black_scholes_value(
        option_type=option_type,
        underlying_price=underlying_price,
        strike=strike,
        days_to_expiration=int(dte),
        volatility=volatility_for_model,
        risk_free_rate=risk_free_rate,
    )
    if not theoretical_result.get("ok"):
        warnings.append("theoretical_value_unavailable")
        return {
            "ok": False,
            "option_contract": option_contract,
            "ticker": ticker,
            "mispricing_label": "mispricing_unknown",
            "mispricing_score": 0.0,
            "market_mid": market_mid,
            "theoretical_value": None,
            "theoretical_edge_percent": None,
            "historical_volatility": hv,
            "implied_volatility": implied_volatility,
            "iv_vs_hv_ratio": None,
            "breakeven_price": _safe_float(option_candidate.get("breakeven_price")),
            "breakeven_move_percent": _safe_float(option_candidate.get("breakeven_move_percent")),
            "underlying_target_price": _safe_float(underlying_candidate.get("target_price")),
            "underlying_target_move_percent": None,
            "target_exceeds_breakeven": None,
            "liquidity_penalty": None,
            "spread_penalty": None,
            "probability_context": {},
            "warnings": warnings,
            "explanation": theoretical_result.get("error", "Unable to calculate theoretical value."),
            "error": theoretical_result.get("error"),
        }

    theoretical_value = _safe_float(theoretical_result.get("theoretical_value")) or 0.0
    theoretical_edge_percent = ((theoretical_value - market_mid) / market_mid * 100.0) if market_mid > 0 else None
    expected_move_context = calculate_expected_move_context(underlying_candidate, option_candidate)
    target_exceeds_breakeven = bool(expected_move_context.get("target_exceeds_breakeven"))

    iv_vs_hv_ratio = None
    if hv not in (None, 0):
        iv_vs_hv_ratio = implied_volatility / hv

    score = 50.0
    if theoretical_edge_percent is not None:
        if theoretical_edge_percent >= 20:
            score += 18
        elif theoretical_edge_percent >= 8:
            score += 10
        elif theoretical_edge_percent >= 0:
            score += 4
        elif theoretical_edge_percent <= -20:
            score -= 22
        elif theoretical_edge_percent <= -8:
            score -= 12
        else:
            score -= 5

    if target_exceeds_breakeven:
        margin = _safe_float(expected_move_context.get("target_vs_breakeven_margin")) or 0.0
        score += 12 if margin > 0 else 6
    else:
        warnings.append("breakeven_above_target")
        score -= 18

    if iv_vs_hv_ratio is not None:
        if iv_vs_hv_ratio > 1.8:
            warnings.append("very_high_iv_vs_hv")
            score -= 18
        elif iv_vs_hv_ratio > 1.35:
            warnings.append("iv_above_hv")
            score -= 10
        elif iv_vs_hv_ratio >= 0.8:
            score += 5
        elif iv_vs_hv_ratio < 0.55:
            score -= 2

    spread_penalty = 0.0
    if spread_percent is None:
        warnings.append("missing_spread_data")
        spread_penalty = 8.0
    elif spread_percent > 0.25:
        warnings.append("extreme_spread")
        spread_penalty = 20.0
    elif spread_percent > 0.15:
        spread_penalty = 12.0
    elif spread_percent > 0.08:
        spread_penalty = 5.0
    else:
        score += 5
    score -= spread_penalty

    liquidity_penalty = 0.0
    if open_interest < 100:
        liquidity_penalty += 10.0
        warnings.append("low_open_interest")
    elif open_interest >= 500:
        score += 4
    if volume < 25:
        liquidity_penalty += 8.0
        warnings.append("low_volume")
    elif volume >= 100:
        score += 3
    score -= liquidity_penalty

    if delta < 0.2:
        warnings.append("low_probability_delta")
        score -= 16
    elif delta < 0.3:
        score -= 8
    elif 0.3 <= delta <= 0.7:
        score += 8
    elif delta > 0.85:
        score -= 4

    if int(dte) < 14:
        warnings.append("too_little_time")
        score -= 12
    elif 14 <= int(dte) <= 56:
        score += 6
    else:
        score -= 3

    probability_context = {
        "delta": delta,
        "days_to_expiration": int(dte),
        "target_exceeds_breakeven": target_exceeds_breakeven,
        "iv_vs_hv_ratio": iv_vs_hv_ratio,
    }

    score = max(0.0, min(100.0, round(score, 2)))
    label = _label_from_score(score, warnings, target_exceeds_breakeven)

    explanation_parts = [f"{option_contract or 'Option'} is labeled {label.replace('_', ' ')}."]
    if theoretical_edge_percent is not None:
        explanation_parts.append(
            f"Theoretical value is {round(theoretical_value, 2)} versus market mid {round(market_mid, 2)}, for an edge of {round(theoretical_edge_percent, 2)}%."
        )
    if iv_vs_hv_ratio is not None:
        explanation_parts.append(f"IV/HV ratio is {round(iv_vs_hv_ratio, 2)}.")
    if target_exceeds_breakeven:
        explanation_parts.append("The underlying target clears the option breakeven.")
    else:
        explanation_parts.append("The underlying target does not clearly clear the option breakeven.")
    if warnings:
        explanation_parts.append(f"Warnings: {', '.join(warnings[:4])}.")

    return {
        "ok": True,
        "option_contract": option_contract,
        "ticker": ticker,
        "mispricing_label": label,
        "mispricing_score": score,
        "market_mid": market_mid,
        "theoretical_value": theoretical_value,
        "theoretical_edge_percent": theoretical_edge_percent,
        "historical_volatility": hv,
        "implied_volatility": implied_volatility,
        "iv_vs_hv_ratio": iv_vs_hv_ratio,
        "breakeven_price": _safe_float(option_candidate.get("breakeven_price")),
        "breakeven_move_percent": _safe_float(option_candidate.get("breakeven_move_percent")),
        "underlying_target_price": expected_move_context.get("underlying_target_price"),
        "underlying_target_move_percent": expected_move_context.get("underlying_target_move_percent"),
        "target_exceeds_breakeven": target_exceeds_breakeven,
        "liquidity_penalty": liquidity_penalty,
        "spread_penalty": spread_penalty,
        "probability_context": probability_context,
        "warnings": warnings,
        "explanation": " ".join(explanation_parts),
        "error": None,
    }


def rank_options_by_value(
    option_candidates: list[dict],
    underlying_candidate: dict,
    historical_volatility: float | None = None,
) -> dict:
    ranked_candidates: list[dict] = []
    for option_candidate in option_candidates or []:
        if not isinstance(option_candidate, dict):
            continue
        mispricing_context = evaluate_option_mispricing(
            option_candidate=option_candidate,
            underlying_candidate=underlying_candidate,
            historical_volatility=historical_volatility,
        )
        candidate_copy = dict(option_candidate)
        candidate_copy["mispricing_context"] = mispricing_context
        candidate_copy["mispricing_label"] = mispricing_context.get("mispricing_label")
        candidate_copy["mispricing_score"] = mispricing_context.get("mispricing_score")
        ranked_candidates.append(candidate_copy)

    ranked_candidates.sort(
        key=lambda candidate: (
            1 if str(candidate.get("recommendation_status", "")).lower() == "recommendable" else 0,
            _safe_float(candidate.get("mispricing_score")) or 0.0,
            _safe_float(candidate.get("score")) or 0.0,
            _safe_float(candidate.get("risk_reward")) or 0.0,
            -(_safe_float(candidate.get("spread_percent")) or 0.0),
            _safe_float(candidate.get("open_interest")) or 0.0,
            _safe_float(candidate.get("volume")) or 0.0,
        ),
        reverse=True,
    )

    for index, candidate in enumerate(ranked_candidates, start=1):
        candidate["value_rank"] = index

    return {
        "ok": True,
        "ticker": str(underlying_candidate.get("ticker") or underlying_candidate.get("underlying_ticker") or "").upper(),
        "historical_volatility": historical_volatility,
        "ranked_candidates": ranked_candidates,
        "error": None,
    }
