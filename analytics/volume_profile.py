from __future__ import annotations

from datetime import datetime, timezone
import math
import os
from typing import Any


APPROXIMATION_WARNING = "Volume profile approximated from daily close/volume data."


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


def _float_env(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, default))
    except (TypeError, ValueError):
        return default


def _int_env(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, default))
    except (TypeError, ValueError):
        return default


def _config(config: dict | None = None) -> dict:
    cfg = {
        "enabled": _bool_env("VOLUME_PROFILE_ENABLED", True),
        "lookback_days": _int_env("VOLUME_PROFILE_LOOKBACK_DAYS", 90),
        "bins": _int_env("VOLUME_PROFILE_BINS", 24),
        "resistance_buffer_pct": _float_env("VOLUME_PROFILE_RESISTANCE_BUFFER_PCT", 0.015),
        "support_buffer_pct": _float_env("VOLUME_PROFILE_SUPPORT_BUFFER_PCT", 0.015),
        "value_area_percent": 0.70,
    }
    if isinstance(config, dict):
        cfg.update(config)
    return cfg


def _bar_close_volume(bar: dict) -> tuple[float | None, float | None]:
    close = _safe_float(bar.get("close") if "close" in bar else bar.get("c"))
    volume = _safe_float(bar.get("volume") if "volume" in bar else bar.get("v"))
    return close, volume


def _zone_from_bin(bin_item: dict) -> dict:
    return {
        "low": bin_item["low"],
        "high": bin_item["high"],
        "mid": bin_item["mid"],
        "volume": bin_item["volume"],
        "volume_percent": bin_item["volume_percent"],
    }


def build_volume_profile(
    price_history: list[dict],
    bins: int = 24,
    lookback_days: int = 90,
    method: str = "close_volume",
) -> dict:
    warnings = [APPROXIMATION_WARNING]
    errors: list[str] = []
    safe_bins = max(int(bins or 24), 4)
    rows = [bar for bar in (price_history or []) if isinstance(bar, dict)][-max(int(lookback_days or 90), 2):]
    close_volume = []
    for bar in rows:
        close, volume = _bar_close_volume(bar)
        if close is not None and close > 0 and volume is not None and volume > 0:
            close_volume.append((close, volume))

    if len(close_volume) < 5:
        return {
            "ok": False,
            "method": method,
            "lookback_days": lookback_days,
            "bins": [],
            "point_of_control": None,
            "value_area_high": None,
            "value_area_low": None,
            "high_volume_nodes": [],
            "low_volume_nodes": [],
            "support_zones": [],
            "resistance_zones": [],
            "warnings": warnings + ["Insufficient valid daily close/volume history for volume profile."],
            "errors": ["Insufficient valid daily close/volume history."],
        }

    closes = [item[0] for item in close_volume]
    min_price = min(closes)
    max_price = max(closes)
    if min_price == max_price:
        return {
            "ok": False,
            "method": method,
            "lookback_days": lookback_days,
            "bins": [],
            "point_of_control": min_price,
            "value_area_high": None,
            "value_area_low": None,
            "high_volume_nodes": [],
            "low_volume_nodes": [],
            "support_zones": [],
            "resistance_zones": [],
            "warnings": warnings + ["Price range is constant; volume profile cannot be binned."],
            "errors": ["Constant price history."],
        }

    width = (max_price - min_price) / safe_bins
    profile_bins = []
    for index in range(safe_bins):
        low = min_price + (width * index)
        high = max_price if index == safe_bins - 1 else low + width
        profile_bins.append({"index": index, "low": round(low, 4), "high": round(high, 4), "mid": round((low + high) / 2, 4), "volume": 0.0})

    for close, volume in close_volume:
        index = min(int((close - min_price) / width), safe_bins - 1)
        profile_bins[index]["volume"] += volume

    total_volume = sum(item["volume"] for item in profile_bins)
    for item in profile_bins:
        item["volume"] = round(item["volume"], 4)
        item["volume_percent"] = round((item["volume"] / total_volume) if total_volume else 0.0, 6)

    sorted_by_volume = sorted(profile_bins, key=lambda item: item["volume"], reverse=True)
    poc_bin = sorted_by_volume[0]
    target_volume = total_volume * 0.70
    accumulated = 0.0
    value_bins = []
    for item in sorted_by_volume:
        value_bins.append(item)
        accumulated += item["volume"]
        if accumulated >= target_volume:
            break

    avg_volume_per_bin = total_volume / safe_bins if safe_bins else 0.0
    high_volume_nodes = [_zone_from_bin(item) for item in profile_bins if item["volume"] >= avg_volume_per_bin * 1.25]
    low_volume_nodes = [_zone_from_bin(item) for item in profile_bins if item["volume"] <= avg_volume_per_bin * 0.50]

    return {
        "ok": True,
        "timestamp": _now_iso(),
        "method": method,
        "lookback_days": lookback_days,
        "bins": profile_bins,
        "point_of_control": poc_bin["mid"],
        "value_area_high": max(item["high"] for item in value_bins),
        "value_area_low": min(item["low"] for item in value_bins),
        "high_volume_nodes": high_volume_nodes,
        "low_volume_nodes": low_volume_nodes,
        "support_zones": high_volume_nodes,
        "resistance_zones": high_volume_nodes,
        "warnings": warnings,
        "errors": errors,
    }


def analyze_price_location_vs_volume_profile(
    current_price: float,
    volume_profile: dict,
    config: dict | None = None,
) -> dict:
    cfg = _config(config)
    price = _safe_float(current_price)
    if price is None or not isinstance(volume_profile, dict) or not volume_profile.get("ok"):
        return {
            "ok": False,
            "price_location": "unknown",
            "nearest_support": None,
            "nearest_resistance": None,
            "distance_to_support_pct": None,
            "distance_to_resistance_pct": None,
            "warnings": ["Volume profile or current price is unavailable."],
        }

    zones = [_zone_from_bin(item) for item in volume_profile.get("high_volume_nodes", []) if isinstance(item, dict)]
    supports = [zone for zone in zones if zone["mid"] <= price]
    resistances = [zone for zone in zones if zone["mid"] >= price]
    nearest_support = max(supports, key=lambda zone: zone["mid"], default=None)
    nearest_resistance = min(resistances, key=lambda zone: zone["mid"], default=None)
    value_low = _safe_float(volume_profile.get("value_area_low"))
    value_high = _safe_float(volume_profile.get("value_area_high"))
    poc = _safe_float(volume_profile.get("point_of_control"))

    if value_low is not None and value_high is not None:
        if price < value_low:
            location = "below_value_area"
        elif price > value_high:
            location = "above_value_area"
        else:
            location = "inside_value_area"
    else:
        location = "unknown"
    if poc is not None and abs(price - poc) / price <= 0.01:
        location = "near_point_of_control"

    distance_to_support = ((price - nearest_support["mid"]) / price) if nearest_support else None
    distance_to_resistance = ((nearest_resistance["mid"] - price) / price) if nearest_resistance else None
    return {
        "ok": True,
        "price_location": location,
        "nearest_support": nearest_support,
        "nearest_resistance": nearest_resistance,
        "distance_to_support_pct": distance_to_support,
        "distance_to_resistance_pct": distance_to_resistance,
        "support_buffer_pct": cfg["support_buffer_pct"],
        "resistance_buffer_pct": cfg["resistance_buffer_pct"],
        "warnings": [],
    }


def evaluate_volume_profile_confirmation(
    candidate: dict,
    price_history: list[dict],
    config: dict | None = None,
) -> dict:
    cfg = _config(config)
    ticker = str((candidate or {}).get("ticker", "")).upper()
    if not cfg["enabled"]:
        return {
            "ok": True,
            "ticker": ticker,
            "confirmation_status": "neutral",
            "price_location": "disabled",
            "point_of_control": None,
            "value_area_high": None,
            "value_area_low": None,
            "nearest_support": None,
            "nearest_resistance": None,
            "risk_reward_adjustment": 0.0,
            "score_adjustment": 0.0,
            "reasons": ["Volume profile confirmation is disabled."],
            "warnings": ["Volume profile confirmation is disabled."],
        }

    profile = build_volume_profile(
        price_history,
        bins=int(cfg["bins"]),
        lookback_days=int(cfg["lookback_days"]),
    )
    current_price = _safe_float((candidate or {}).get("current_price") or (candidate or {}).get("entry_price"))
    location = analyze_price_location_vs_volume_profile(current_price, profile, config=cfg)
    if not profile.get("ok") or not location.get("ok"):
        return {
            "ok": True,
            "ticker": ticker,
            "confirmation_status": "neutral",
            "price_location": "unknown",
            "point_of_control": profile.get("point_of_control"),
            "value_area_high": profile.get("value_area_high"),
            "value_area_low": profile.get("value_area_low"),
            "nearest_support": None,
            "nearest_resistance": None,
            "risk_reward_adjustment": 0.0,
            "score_adjustment": 0.0,
            "volume_profile": profile,
            "reasons": ["Volume profile confirmation is neutral because profile data is unavailable."],
            "warnings": list(profile.get("warnings", [])) + list(location.get("warnings", [])),
        }

    direction = str((candidate or {}).get("direction", "long")).lower()
    support_distance = _safe_float(location.get("distance_to_support_pct"))
    resistance_distance = _safe_float(location.get("distance_to_resistance_pct"))
    price_location = location.get("price_location")
    status = "neutral"
    score_adjustment = 0.0
    risk_reward_adjustment = 0.0
    reasons: list[str] = []
    warnings = list(profile.get("warnings", []))

    if direction == "short":
        if resistance_distance is not None and resistance_distance <= float(cfg["resistance_buffer_pct"]):
            status = "confirmed"
            score_adjustment = 5.0
            reasons.append("Short candidate is near high-volume resistance.")
        elif support_distance is not None and support_distance <= float(cfg["support_buffer_pct"]):
            status = "warning"
            score_adjustment = -8.0
            reasons.append("Short candidate is close to high-volume support.")
        elif price_location == "below_value_area":
            status = "warning"
            score_adjustment = -5.0
            reasons.append("Short candidate is extended below the value area.")
    else:
        near_support = support_distance is not None and support_distance <= float(cfg["support_buffer_pct"])
        if support_distance is not None and support_distance <= float(cfg["support_buffer_pct"]):
            status = "confirmed"
            score_adjustment = 5.0
            risk_reward_adjustment = 0.1
            reasons.append("Long candidate is near high-volume support.")
        if not near_support and resistance_distance is not None and resistance_distance <= float(cfg["resistance_buffer_pct"]):
            status = "warning" if status != "confirmed" else "warning"
            score_adjustment = min(score_adjustment, -8.0)
            risk_reward_adjustment = min(risk_reward_adjustment, -0.2)
            reasons.append("Long candidate is directly below high-volume resistance.")
        if price_location == "above_value_area":
            status = "warning"
            score_adjustment = min(score_adjustment, -6.0)
            reasons.append("Long candidate is extended above the value area.")
    if status == "neutral" and not reasons:
        reasons.append("Price location versus volume profile is neutral.")

    return {
        "ok": True,
        "ticker": ticker,
        "confirmation_status": status,
        "price_location": price_location,
        "point_of_control": profile.get("point_of_control"),
        "value_area_high": profile.get("value_area_high"),
        "value_area_low": profile.get("value_area_low"),
        "nearest_support": location.get("nearest_support"),
        "nearest_resistance": location.get("nearest_resistance"),
        "risk_reward_adjustment": risk_reward_adjustment,
        "score_adjustment": score_adjustment,
        "volume_profile": profile,
        "reasons": reasons,
        "warnings": warnings,
    }
