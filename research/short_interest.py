from __future__ import annotations

from typing import Any


def _safe_float(value: Any) -> float | None:
    try:
        if value is None or str(value).strip() == "":
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _field(payload: dict | None, *names: str) -> Any:
    if not isinstance(payload, dict):
        return None
    for name in names:
        if name in payload:
            return payload[name]
    return None


def _short_interest_level(percent_float: float | None) -> str:
    if percent_float is None:
        return "unknown"
    if percent_float < 5:
        return "low"
    if percent_float < 15:
        return "medium"
    if percent_float <= 25:
        return "high"
    return "extreme"


def _squeeze_level(days_to_cover: float | None, short_level: str, relative_volume: float | None) -> str:
    if days_to_cover is None and short_level == "unknown":
        return "unknown"
    level = "low"
    if short_level in {"high", "extreme"}:
        level = "medium"
    if days_to_cover is not None:
        if days_to_cover > 10:
            level = "extreme"
        elif days_to_cover > 5:
            level = "high"
        elif days_to_cover >= 3 and level == "low":
            level = "medium"
    if relative_volume is not None and relative_volume >= 1.8 and level in {"medium", "high"}:
        return "high" if level == "medium" else "extreme"
    return level


def _trend_is_strong(market_snapshot: dict | None) -> bool:
    if not isinstance(market_snapshot, dict):
        return False
    data = market_snapshot.get("data") if isinstance(market_snapshot.get("data"), dict) else market_snapshot
    technical = data.get("technical_snapshot") if isinstance(data, dict) and isinstance(data.get("technical_snapshot"), dict) else data
    current = _safe_float(_field(technical, "current_price", "close", "last_price"))
    sma20 = _safe_float(_field(technical, "sma_20", "sma20"))
    sma50 = _safe_float(_field(technical, "sma_50", "sma50"))
    relative_volume = _safe_float(_field(technical, "relative_volume"))
    high20 = _safe_float(_field(technical, "high_20", "high20"))
    return (
        current is not None
        and sma20 is not None
        and sma50 is not None
        and current > sma20
        and current > sma50
        and (relative_volume is None or relative_volume >= 1.2)
        and (high20 is None or current >= high20 * 0.98)
    )


def evaluate_short_interest(
    ticker: str,
    short_data: dict | None = None,
    market_snapshot: dict | None = None,
    config: dict | None = None,
) -> dict:
    normalized = str(ticker or "").strip().upper()
    percent_float = _safe_float(_field(short_data, "short_interest_percent_float", "short_percent_float", "short_float_percent"))
    days_to_cover = _safe_float(_field(short_data, "days_to_cover", "short_ratio"))
    borrow_rate = _safe_float(_field(short_data, "borrow_rate", "fee_rate", "borrow_fee_rate"))
    direction = str(_field(config, "direction") or _field(short_data, "direction") or "long").lower()
    setup_type = str(_field(config, "setup_type") or _field(short_data, "setup_type") or "").lower()
    relative_volume = _safe_float(_field(short_data, "relative_volume"))
    if relative_volume is None and isinstance(market_snapshot, dict):
        data = market_snapshot.get("data") if isinstance(market_snapshot.get("data"), dict) else market_snapshot
        technical = data.get("technical_snapshot") if isinstance(data, dict) and isinstance(data.get("technical_snapshot"), dict) else data
        relative_volume = _safe_float(_field(technical, "relative_volume"))

    warnings: list[str] = []
    reasons: list[str] = []
    errors: list[str] = []
    short_level = _short_interest_level(percent_float)
    squeeze_risk = _squeeze_level(days_to_cover, short_level, relative_volume)

    if percent_float is None and days_to_cover is None and borrow_rate is None:
        warnings.append("Short-interest data is unavailable; no short-interest adjustment applied.")
        return {
            "ok": True,
            "ticker": normalized,
            "short_interest_percent_float": None,
            "days_to_cover": None,
            "borrow_rate": None,
            "short_interest_level": "unknown",
            "squeeze_risk": "unknown",
            "trade_impact": "unknown",
            "risk_multiplier": 1.0,
            "score_adjustment": 0.0,
            "reasons": [],
            "warnings": warnings,
            "errors": errors,
        }

    strong_trend = _trend_is_strong(market_snapshot)
    trade_impact = "neutral"
    risk_multiplier = 1.0
    score_adjustment = 0.0

    if direction == "short" and short_level in {"high", "extreme"}:
        trade_impact = "blocking" if short_level == "extreme" or squeeze_risk in {"high", "extreme"} else "caution"
        risk_multiplier = 0.0 if trade_impact == "blocking" else 0.5
        score_adjustment = -25.0 if trade_impact == "blocking" else -10.0
        reasons.append("High short interest creates squeeze risk for short candidates.")
    elif short_level == "extreme":
        if strong_trend or setup_type in {"momentum_breakout", "relative_strength"}:
            trade_impact = "supportive"
            risk_multiplier = 0.85
            score_adjustment = 4.0
            reasons.append("Extreme short interest may support a long momentum/squeeze setup, but risk remains elevated.")
        else:
            trade_impact = "caution"
            risk_multiplier = 0.65
            score_adjustment = -8.0
            reasons.append("Extreme short interest is risky without strong long momentum confirmation.")
    elif short_level == "high":
        if strong_trend or setup_type in {"momentum_breakout", "relative_strength"}:
            trade_impact = "supportive"
            risk_multiplier = 0.95
            score_adjustment = 2.0
            reasons.append("High short interest can support a long momentum squeeze setup.")
        else:
            trade_impact = "caution"
            risk_multiplier = 0.8
            score_adjustment = -4.0
            reasons.append("High short interest warrants caution for weaker long setups.")
    elif short_level == "medium":
        trade_impact = "neutral"
        reasons.append("Short interest is moderate.")
    else:
        trade_impact = "neutral"
        reasons.append("Short interest is low.")

    if squeeze_risk in {"high", "extreme"} and trade_impact == "neutral":
        trade_impact = "caution"
        risk_multiplier = min(risk_multiplier, 0.85)
        score_adjustment -= 2.0
        reasons.append("Days-to-cover indicates elevated squeeze/crowding risk.")

    return {
        "ok": True,
        "ticker": normalized,
        "short_interest_percent_float": percent_float,
        "days_to_cover": days_to_cover,
        "borrow_rate": borrow_rate,
        "short_interest_level": short_level,
        "squeeze_risk": squeeze_risk,
        "trade_impact": trade_impact,
        "risk_multiplier": round(risk_multiplier, 4),
        "score_adjustment": round(score_adjustment, 2),
        "reasons": reasons,
        "warnings": warnings,
        "errors": errors,
    }


def evaluate_borrow_pressure(
    ticker: str,
    borrow_data: dict | None = None,
    config: dict | None = None,
) -> dict:
    borrow_rate = _safe_float(_field(borrow_data, "borrow_rate", "fee_rate", "borrow_fee_rate"))
    available_raw = _field(borrow_data, "borrow_available", "available", "is_available")
    borrow_available = None if available_raw is None else str(available_raw).strip().lower() in {"1", "true", "yes", "y", "on"}
    warnings: list[str] = []
    errors: list[str] = []

    if borrow_rate is None and borrow_available is None:
        warnings.append("Borrow data is unavailable; short trades should require a separate borrow check.")
        pressure = "unknown"
        short_allowed = True
    elif borrow_available is False:
        pressure = "extreme"
        short_allowed = False
    elif borrow_rate is None:
        pressure = "unknown"
        short_allowed = True
    elif borrow_rate < 3:
        pressure = "low"
        short_allowed = True
    elif borrow_rate < 10:
        pressure = "medium"
        short_allowed = True
    elif borrow_rate < 25:
        pressure = "high"
        short_allowed = False
    else:
        pressure = "extreme"
        short_allowed = False

    if pressure in {"high", "extreme"}:
        warnings.append("Borrow pressure blocks short-style candidates.")

    return {
        "ok": True,
        "ticker": str(ticker or "").strip().upper(),
        "borrow_rate": borrow_rate,
        "borrow_available": borrow_available,
        "borrow_pressure": pressure,
        "short_trade_allowed": short_allowed,
        "warnings": warnings,
        "errors": errors,
    }
