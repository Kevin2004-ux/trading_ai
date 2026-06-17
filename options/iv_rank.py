from __future__ import annotations

import math
from copy import deepcopy
from typing import Any


DEFAULT_IV_CONFIG = {
    "lookback_days": 252,
    "cheap_threshold": 20.0,
    "normal_threshold": 60.0,
    "elevated_threshold": 80.0,
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
    merged = deepcopy(DEFAULT_IV_CONFIG)
    if isinstance(config, dict):
        merged.update(config)
    return merged


def _clean_history(values: list[float] | None, lookback_days: int) -> list[float]:
    if not isinstance(values, list):
        return []
    cleaned = [value for value in (_safe_float(item) for item in values) if value is not None and value > 0]
    return cleaned[-max(int(lookback_days or 0), 1):]


def calculate_iv_rank(
    current_iv: float,
    historical_iv_values: list[float],
    lookback_days: int = 252,
) -> dict:
    current = _safe_float(current_iv)
    history = _clean_history(historical_iv_values, lookback_days)
    if current is None or current <= 0:
        return {
            "ok": False,
            "current_iv": current,
            "iv_rank": None,
            "lookback_days": lookback_days,
            "sample_size": len(history),
            "warnings": [],
            "errors": ["Current IV is required to calculate IV rank."],
        }
    if len(history) < 2:
        return {
            "ok": False,
            "current_iv": current,
            "iv_rank": None,
            "lookback_days": lookback_days,
            "sample_size": len(history),
            "warnings": ["Historical IV sample is too small for IV rank."],
            "errors": ["At least two historical IV values are required."],
        }

    iv_min = min(history)
    iv_max = max(history)
    if iv_max <= iv_min:
        rank = 50.0
    else:
        rank = ((current - iv_min) / (iv_max - iv_min)) * 100.0
    rank = round(max(0.0, min(rank, 100.0)), 2)
    return {
        "ok": True,
        "current_iv": current,
        "iv_rank": rank,
        "lookback_days": lookback_days,
        "sample_size": len(history),
        "warnings": [],
        "errors": [],
    }


def calculate_iv_percentile(
    current_iv: float,
    historical_iv_values: list[float],
    lookback_days: int = 252,
) -> dict:
    current = _safe_float(current_iv)
    history = _clean_history(historical_iv_values, lookback_days)
    if current is None or current <= 0:
        return {
            "ok": False,
            "current_iv": current,
            "iv_percentile": None,
            "lookback_days": lookback_days,
            "sample_size": len(history),
            "warnings": [],
            "errors": ["Current IV is required to calculate IV percentile."],
        }
    if not history:
        return {
            "ok": False,
            "current_iv": current,
            "iv_percentile": None,
            "lookback_days": lookback_days,
            "sample_size": 0,
            "warnings": ["Historical IV sample is unavailable for IV percentile."],
            "errors": ["Historical IV values are required."],
        }

    lower_or_equal = sum(1 for value in history if value <= current)
    percentile = round((lower_or_equal / len(history)) * 100.0, 2)
    return {
        "ok": True,
        "current_iv": current,
        "iv_percentile": percentile,
        "lookback_days": lookback_days,
        "sample_size": len(history),
        "warnings": [],
        "errors": [],
    }


def _context_from_rank(iv_rank: float | None, cfg: dict) -> tuple[str, str]:
    if iv_rank is None:
        return "unknown", "unknown"
    if iv_rank < cfg["cheap_threshold"]:
        return "cheap", "long_premium_favorable"
    if iv_rank < cfg["normal_threshold"]:
        return "normal", "long_premium_favorable"
    if iv_rank < cfg["elevated_threshold"]:
        return "elevated", "short_premium_favorable"
    return "expensive", "short_premium_favorable"


def evaluate_iv_context(
    current_iv: float | None,
    historical_iv_values: list[float] | None = None,
    config: dict | None = None,
) -> dict:
    cfg = _merge_config(config)
    lookback_days = int(cfg.get("lookback_days") or 252)
    current = _safe_float(current_iv)
    warnings: list[str] = []
    errors: list[str] = []

    if current is None or current <= 0:
        return {
            "ok": False,
            "current_iv": current,
            "iv_rank": None,
            "iv_percentile": None,
            "lookback_days": lookback_days,
            "iv_context": "unknown",
            "trade_bias": "unknown",
            "warnings": ["Missing implied volatility blocks final option recommendations."],
            "errors": ["Current IV is required."],
        }

    precomputed_rank = _safe_float(
        (config or {}).get("iv_rank")
        if isinstance(config, dict)
        else None
    )
    if precomputed_rank is None and isinstance(config, dict):
        precomputed_rank = _safe_float(config.get("precomputed_iv_rank"))
    precomputed_percentile = _safe_float((config or {}).get("iv_percentile") if isinstance(config, dict) else None)

    rank_result = calculate_iv_rank(current, historical_iv_values or [], lookback_days=lookback_days)
    percentile_result = calculate_iv_percentile(current, historical_iv_values or [], lookback_days=lookback_days)

    iv_rank = _safe_float(rank_result.get("iv_rank"))
    iv_percentile = _safe_float(percentile_result.get("iv_percentile"))
    if iv_rank is None and precomputed_rank is not None:
        iv_rank = round(max(0.0, min(precomputed_rank, 100.0)), 2)
        warnings.append("Using provider-supplied IV rank because historical IV history is unavailable.")
    if iv_percentile is None and precomputed_percentile is not None:
        iv_percentile = round(max(0.0, min(precomputed_percentile, 100.0)), 2)
        warnings.append("Using provider-supplied IV percentile because historical IV history is unavailable.")

    if iv_rank is None:
        warnings.extend(rank_result.get("warnings", []))
        errors.extend(rank_result.get("errors", []))
    if iv_percentile is None:
        warnings.extend(percentile_result.get("warnings", []))

    iv_context, trade_bias = _context_from_rank(iv_rank, cfg)
    ok = iv_rank is not None
    return {
        "ok": ok,
        "current_iv": current,
        "iv_rank": iv_rank,
        "iv_percentile": iv_percentile,
        "lookback_days": lookback_days,
        "iv_context": iv_context,
        "trade_bias": trade_bias,
        "warnings": warnings,
        "errors": [] if ok else (errors or ["IV rank/percentile context is unavailable."]),
    }

