from __future__ import annotations

import math
from copy import deepcopy
from typing import Any


DEFAULT_GREEKS_CONFIG = {
    "extreme_delta": 0.85,
    "low_delta": 0.15,
    "high_gamma": 0.18,
    "near_expiration_days": 7,
    "high_theta_to_premium": 0.08,
    "portfolio_max_abs_delta": 3.0,
    "portfolio_max_abs_gamma": 0.6,
    "portfolio_max_abs_vega": 1.5,
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
    merged = deepcopy(DEFAULT_GREEKS_CONFIG)
    if isinstance(config, dict):
        merged.update(config)
    return merged


def _contract(option_quote: dict) -> str:
    return str(option_quote.get("option_contract") or option_quote.get("ticker") or "").upper()


def evaluate_option_greeks(
    option_quote: dict,
    config: dict | None = None,
) -> dict:
    cfg = _merge_config(config)
    quote = option_quote if isinstance(option_quote, dict) else {}
    contract = _contract(quote)
    delta = _safe_float(quote.get("delta"))
    gamma = _safe_float(quote.get("gamma"))
    theta = _safe_float(quote.get("theta"))
    vega = _safe_float(quote.get("vega"))
    rho = _safe_float(quote.get("rho"))
    dte = _safe_float(quote.get("days_to_expiration"))
    premium = _safe_float(quote.get("mid")) or _safe_float(quote.get("last"))

    warnings: list[str] = []
    errors: list[str] = []

    if delta is None:
        return {
            "ok": False,
            "contract": contract,
            "delta": None,
            "gamma": gamma,
            "theta": theta,
            "vega": vega,
            "rho": rho,
            "greeks_quality": "unavailable",
            "risk_level": "blocked",
            "warnings": ["Missing delta blocks final option recommendations."],
            "errors": ["Delta is required."],
        }

    missing_secondary = [name for name, value in (("gamma", gamma), ("theta", theta), ("vega", vega)) if value is None]
    if missing_secondary:
        warnings.append(f"Missing secondary Greeks: {', '.join(missing_secondary)}.")

    abs_delta = abs(delta)
    if abs_delta >= cfg["extreme_delta"]:
        warnings.append("Extreme delta creates stock-like option exposure.")
    elif abs_delta <= cfg["low_delta"]:
        warnings.append("Very low delta suggests a speculative low-probability contract.")

    high_gamma_near_expiration = (
        gamma is not None
        and dte is not None
        and dte <= cfg["near_expiration_days"]
        and abs(gamma) >= cfg["high_gamma"]
    )
    if high_gamma_near_expiration:
        warnings.append("High gamma near expiration creates unstable option risk.")

    if theta is not None and premium not in (None, 0):
        theta_ratio = abs(theta) / premium
        if theta < 0 and theta_ratio >= cfg["high_theta_to_premium"]:
            warnings.append("Negative theta is high relative to premium for a long-premium trade.")

    if len(missing_secondary) >= 2:
        greeks_quality = "poor"
    elif missing_secondary:
        greeks_quality = "usable"
    elif warnings:
        greeks_quality = "usable"
    else:
        greeks_quality = "good"

    risk_level = "low"
    if high_gamma_near_expiration:
        risk_level = "high"
    elif abs_delta >= cfg["extreme_delta"] or abs_delta <= cfg["low_delta"] or warnings:
        risk_level = "medium"
    if greeks_quality == "poor":
        risk_level = "blocked"
        errors.append("Usable delta, gamma, theta, and vega are required for final option eligibility.")

    return {
        "ok": greeks_quality in {"good", "usable"} and risk_level != "blocked",
        "contract": contract,
        "delta": delta,
        "gamma": gamma,
        "theta": theta,
        "vega": vega,
        "rho": rho,
        "greeks_quality": greeks_quality,
        "risk_level": risk_level,
        "warnings": warnings,
        "errors": errors,
    }


def evaluate_portfolio_greeks(
    open_option_trades: list[dict],
    config: dict | None = None,
) -> dict:
    cfg = _merge_config(config)
    trades = [item for item in (open_option_trades or []) if isinstance(item, dict)]
    totals = {"delta": 0.0, "gamma": 0.0, "theta": 0.0, "vega": 0.0, "rho": 0.0}
    evaluated = []
    warnings: list[str] = []
    errors: list[str] = []

    for trade in trades:
        quantity = _safe_float(trade.get("quantity")) or _safe_float(trade.get("contracts")) or 1.0
        side = -1.0 if str(trade.get("direction", "long")).lower() == "short" else 1.0
        greeks = evaluate_option_greeks(trade, config=cfg)
        evaluated.append({"contract": greeks.get("contract"), "quantity": quantity, "greeks": greeks})
        for key in totals:
            value = _safe_float(greeks.get(key))
            if value is not None:
                totals[key] += value * quantity * side
        warnings.extend(str(item) for item in greeks.get("warnings", []))
        errors.extend(str(item) for item in greeks.get("errors", []))

    risk_level = "low"
    if abs(totals["delta"]) > cfg["portfolio_max_abs_delta"]:
        warnings.append("Portfolio option delta exposure is above the configured limit.")
        risk_level = "high"
    if abs(totals["gamma"]) > cfg["portfolio_max_abs_gamma"]:
        warnings.append("Portfolio option gamma exposure is above the configured limit.")
        risk_level = "high"
    if abs(totals["vega"]) > cfg["portfolio_max_abs_vega"]:
        warnings.append("Portfolio option vega exposure is above the configured limit.")
        risk_level = "medium" if risk_level == "low" else risk_level
    if errors:
        risk_level = "blocked"

    return {
        "ok": not errors,
        "contract": "portfolio",
        "delta": round(totals["delta"], 4),
        "gamma": round(totals["gamma"], 4),
        "theta": round(totals["theta"], 4),
        "vega": round(totals["vega"], 4),
        "rho": round(totals["rho"], 4),
        "greeks_quality": "good" if not warnings and not errors else ("poor" if errors else "usable"),
        "risk_level": risk_level,
        "evaluated_contracts": evaluated,
        "warnings": warnings,
        "errors": errors,
    }

