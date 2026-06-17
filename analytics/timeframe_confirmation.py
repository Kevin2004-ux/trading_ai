from __future__ import annotations

from datetime import datetime, timezone
import math
import os
from typing import Any


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _safe_float(value: Any) -> float | None:
    try:
        if value is None:
            return None
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    if math.isnan(numeric):
        return None
    return numeric


def _bool_env(name: str, default: bool) -> bool:
    return str(os.getenv(name, str(default))).strip().lower() in {"1", "true", "yes", "on"}


def _config(config: dict | None = None) -> dict:
    cfg = {
        "enabled": _bool_env("TIMEFRAME_CONFIRMATION_ENABLED", True),
        "require_weekly_confirmation": _bool_env("REQUIRE_WEEKLY_CONFIRMATION", False),
        "reject_strong_conflict": _bool_env("TIMEFRAME_REJECT_STRONG_CONFLICT", True),
    }
    if isinstance(config, dict):
        cfg.update(config)
    return cfg


def _bars(history: list[dict] | None) -> list[dict]:
    output = []
    for bar in history or []:
        if not isinstance(bar, dict):
            continue
        close = _safe_float(bar.get("close") if "close" in bar else bar.get("c"))
        high = _safe_float(bar.get("high") if "high" in bar else bar.get("h"))
        low = _safe_float(bar.get("low") if "low" in bar else bar.get("l"))
        volume = _safe_float(bar.get("volume") if "volume" in bar else bar.get("v"))
        if close is None:
            continue
        output.append({"close": close, "high": high or close, "low": low or close, "volume": volume or 0.0})
    return output


def _sma(values: list[float], window: int) -> float | None:
    if len(values) < window:
        return None
    return sum(values[-window:]) / window


def _trend_from_bars(rows: list[dict], fast: int, medium: int, slow: int) -> tuple[str, float, list[str]]:
    warnings: list[str] = []
    if len(rows) < max(medium, 5):
        return "unknown", 0.0, ["Insufficient history for trend analysis."]
    closes = [row["close"] for row in rows]
    sma_fast = _sma(closes, fast)
    sma_medium = _sma(closes, medium)
    sma_slow = _sma(closes, slow)
    current = closes[-1]
    recent_highs = [row["high"] for row in rows[-6:]]
    recent_lows = [row["low"] for row in rows[-6:]]
    higher_structure = recent_highs[-1] >= max(recent_highs[:3]) and recent_lows[-1] >= min(recent_lows[:3])
    lower_structure = recent_highs[-1] <= max(recent_highs[:3]) and recent_lows[-1] <= min(recent_lows[:3])

    if sma_fast is not None and sma_medium is not None and current > sma_fast > sma_medium and higher_structure:
        return "uptrend", 80.0, warnings
    if sma_fast is not None and sma_medium is not None and current < sma_fast < sma_medium and lower_structure:
        return "downtrend", -80.0, warnings
    if sma_slow is not None and current > sma_medium and sma_medium > sma_slow:
        return "uptrend", 60.0, warnings
    if sma_slow is not None and current < sma_medium and sma_medium < sma_slow:
        return "downtrend", -60.0, warnings
    return "range", 10.0, warnings


def _momentum_score(rows: list[dict]) -> tuple[float, list[str]]:
    warnings: list[str] = []
    if len(rows) < 21:
        return 0.0, ["Insufficient history for momentum and volume confirmation."]
    closes = [row["close"] for row in rows]
    volumes = [row["volume"] for row in rows]
    current = closes[-1]
    previous = closes[-6]
    return_5 = ((current - previous) / previous) * 100.0 if previous else 0.0
    avg_volume = sum(volumes[-21:-1]) / 20 if len(volumes) >= 21 else 0.0
    relative_volume = volumes[-1] / avg_volume if avg_volume else 1.0
    score = max(-40.0, min(40.0, return_5 * 4.0))
    if relative_volume >= 1.2 and return_5 > 0:
        score += 10.0
    elif relative_volume >= 1.2 and return_5 < 0:
        score -= 10.0
    return round(score, 2), warnings


def build_timeframe_features(
    daily_history: list[dict],
    weekly_history: list[dict] | None = None,
    config: dict | None = None,
) -> dict:
    del config
    daily_rows = _bars(daily_history)
    weekly_rows = _bars(weekly_history)
    daily_trend, daily_score, daily_warnings = _trend_from_bars(daily_rows, 20, 50, 200)
    if weekly_history is None:
        weekly_trend, weekly_score, weekly_warnings = "unknown", 0.0, ["Weekly history unavailable; weekly confirmation is neutral."]
    else:
        weekly_trend, weekly_score, weekly_warnings = _trend_from_bars(weekly_rows, 10, 20, 40)
    momentum, momentum_warnings = _momentum_score(daily_rows)
    return {
        "ok": bool(daily_rows),
        "timestamp": _now_iso(),
        "daily_trend": daily_trend,
        "weekly_trend": weekly_trend,
        "daily_trend_score": daily_score,
        "weekly_trend_score": weekly_score,
        "momentum_score": momentum,
        "daily_rows": len(daily_rows),
        "weekly_rows": len(weekly_rows),
        "warnings": daily_warnings + weekly_warnings + momentum_warnings,
        "errors": [] if daily_rows else ["Daily history unavailable."],
    }


def evaluate_timeframe_confirmation(
    candidate: dict,
    daily_history: list[dict],
    weekly_history: list[dict] | None = None,
    config: dict | None = None,
) -> dict:
    cfg = _config(config)
    ticker = str((candidate or {}).get("ticker", "")).upper()
    direction = str((candidate or {}).get("direction", "long")).lower()
    if not cfg["enabled"]:
        return {
            "ok": True,
            "ticker": ticker,
            "confirmation_status": "neutral",
            "daily_trend": "unknown",
            "weekly_trend": "unknown",
            "daily_alignment": False,
            "weekly_alignment": False,
            "trend_score": 0.0,
            "momentum_score": 0.0,
            "score_adjustment": 0.0,
            "risk_multiplier": 1.0,
            "reasons": ["Timeframe confirmation is disabled."],
            "warnings": ["Timeframe confirmation is disabled."],
        }

    features = build_timeframe_features(daily_history, weekly_history, config=cfg)
    daily_preferred = "downtrend" if direction == "short" else "uptrend"
    daily_conflict = "uptrend" if direction == "short" else "downtrend"
    daily_alignment = features["daily_trend"] == daily_preferred
    weekly_alignment = features["weekly_trend"] == daily_preferred
    weekly_conflict = features["weekly_trend"] == daily_conflict
    trend_score = features["daily_trend_score"] + (features["weekly_trend_score"] * 0.75)
    if direction == "short":
        trend_score = -trend_score
    momentum = features["momentum_score"] if direction != "short" else -features["momentum_score"]

    status = "neutral"
    score_adjustment = 0.0
    risk_multiplier = 1.0
    reasons: list[str] = []
    if daily_alignment and weekly_alignment:
        status = "confirmed"
        score_adjustment = 7.0
        reasons.append("Daily and weekly trends align with candidate direction.")
    elif daily_alignment and features["weekly_trend"] in {"unknown", "range"}:
        status = "neutral"
        score_adjustment = 3.0
        reasons.append("Daily trend aligns while weekly confirmation is neutral or unavailable.")
    elif features["daily_trend"] == daily_conflict and (weekly_conflict or cfg["reject_strong_conflict"]):
        status = "rejected"
        score_adjustment = -25.0
        risk_multiplier = 0.0
        reasons.append("Daily and/or weekly trend strongly conflicts with candidate direction.")
    elif weekly_conflict:
        status = "warning"
        score_adjustment = -10.0
        risk_multiplier = 0.5
        reasons.append("Weekly trend conflicts with candidate direction.")
    elif cfg["require_weekly_confirmation"] and not weekly_alignment:
        status = "warning"
        score_adjustment = -8.0
        risk_multiplier = 0.75
        reasons.append("Weekly confirmation is required but not aligned.")
    else:
        reasons.append("Timeframe confirmation is neutral.")

    if momentum >= 15 and status in {"confirmed", "neutral"}:
        score_adjustment += 2.0
        reasons.append("Recent momentum and volume are supportive.")
    elif momentum <= -15 and status != "rejected":
        status = "warning"
        score_adjustment -= 5.0
        risk_multiplier = min(risk_multiplier, 0.75)
        reasons.append("Recent momentum is not supportive.")

    return {
        "ok": True,
        "ticker": ticker,
        "confirmation_status": status,
        "daily_trend": features["daily_trend"],
        "weekly_trend": features["weekly_trend"],
        "daily_alignment": daily_alignment,
        "weekly_alignment": weekly_alignment,
        "trend_score": round(trend_score, 2),
        "momentum_score": momentum,
        "score_adjustment": round(score_adjustment, 2),
        "risk_multiplier": round(risk_multiplier, 4),
        "features": features,
        "reasons": reasons,
        "warnings": features.get("warnings", []),
    }
