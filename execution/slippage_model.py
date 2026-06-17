from __future__ import annotations

from typing import Any


DEFAULT_STOCK_SLIPPAGE_CONFIG = {
    "mega_cap_high_liquidity_slippage_percent": 0.03,
    "large_cap_liquid_slippage_percent": 0.06,
    "mid_cap_normal_slippage_percent": 0.12,
    "low_liquidity_slippage_percent": 0.35,
    "unknown_slippage_percent": 0.18,
    "max_participation_before_warning": 0.01,
}

DEFAULT_OPTION_SLIPPAGE_CONFIG = {
    "tight_spread_threshold": 0.05,
    "normal_spread_threshold": 0.12,
    "wide_spread_threshold": 0.25,
    "tight_spread_fraction": 0.25,
    "normal_spread_fraction": 0.40,
    "wide_spread_fraction": 0.70,
}


def _safe_float(value: Any) -> float | None:
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _ticker(value: Any) -> str:
    return str(value or "").strip().upper()


def _merge_config(defaults: dict, config: dict | None) -> dict:
    merged = dict(defaults)
    if isinstance(config, dict):
        merged.update(config)
    return merged


def _market_data(market_snapshot: dict | None) -> dict:
    if not isinstance(market_snapshot, dict):
        return {}
    data = market_snapshot.get("data")
    return data if isinstance(data, dict) else market_snapshot


def _metric(trade: dict, market_snapshot: dict | None, key: str) -> float | None:
    value = _safe_float(trade.get(key))
    if value is not None:
        return value
    data = _market_data(market_snapshot)
    technical = data.get("technical_snapshot") if isinstance(data.get("technical_snapshot"), dict) else {}
    return _safe_float(technical.get(key))


def classify_liquidity_tier(
    trade: dict,
    market_snapshot: dict | None = None,
) -> dict:
    if not isinstance(trade, dict):
        return {
            "ok": False,
            "ticker": "",
            "liquidity_tier": "unknown",
            "warnings": [],
            "error": "Trade must be a dictionary.",
        }

    avg_volume = _metric(trade, market_snapshot, "average_volume_20")
    relative_volume = _metric(trade, market_snapshot, "relative_volume")
    atr_percent = _metric(trade, market_snapshot, "atr_percent")
    warnings: list[str] = []

    if avg_volume is None:
        return {
            "ok": True,
            "ticker": _ticker(trade.get("ticker")),
            "liquidity_tier": "unknown",
            "average_volume_20": None,
            "relative_volume": relative_volume,
            "atr_percent": atr_percent,
            "warnings": ["Average volume is unavailable; using unknown liquidity assumptions."],
            "error": None,
        }

    if avg_volume >= 20_000_000 and (relative_volume is None or relative_volume >= 0.7):
        tier = "mega_cap_high_liquidity"
    elif avg_volume >= 5_000_000:
        tier = "large_cap_liquid"
    elif avg_volume >= 1_000_000:
        tier = "mid_cap_normal"
    else:
        tier = "low_liquidity"

    if atr_percent is not None and atr_percent > 8:
        warnings.append("ATR percent is high; slippage assumptions may be optimistic.")

    return {
        "ok": True,
        "ticker": _ticker(trade.get("ticker")),
        "liquidity_tier": tier,
        "average_volume_20": avg_volume,
        "relative_volume": relative_volume,
        "atr_percent": atr_percent,
        "warnings": warnings,
        "error": None,
    }


def estimate_market_impact(
    trade: dict,
    position_sizing: dict | None = None,
    market_snapshot: dict | None = None,
) -> dict:
    if not isinstance(trade, dict):
        return {"ok": False, "market_impact_percent": None, "participation_rate": None, "warnings": [], "error": "Trade must be a dictionary."}

    entry_price = _safe_float(trade.get("entry_price"))
    avg_volume = _metric(trade, market_snapshot, "average_volume_20")
    shares = _safe_float((position_sizing or {}).get("shares"))
    notional = _safe_float((position_sizing or {}).get("notional_exposure"))
    if shares is None and notional is not None and entry_price not in (None, 0):
        shares = notional / entry_price
    if shares is None:
        shares = 100.0

    warnings: list[str] = []
    if avg_volume in (None, 0):
        return {
            "ok": True,
            "market_impact_percent": 0.05,
            "participation_rate": None,
            "warnings": ["Average volume unavailable; using default market impact estimate."],
            "error": None,
        }

    participation_rate = max(shares / avg_volume, 0.0)
    market_impact_percent = min(1.0, participation_rate * 25.0)
    if participation_rate > DEFAULT_STOCK_SLIPPAGE_CONFIG["max_participation_before_warning"]:
        warnings.append("Estimated participation rate is high for a paper fill.")

    return {
        "ok": True,
        "market_impact_percent": market_impact_percent,
        "participation_rate": participation_rate,
        "warnings": warnings,
        "error": None,
    }


def estimate_stock_slippage(
    trade: dict,
    market_snapshot: dict | None = None,
    config: dict | None = None,
) -> dict:
    cfg = _merge_config(DEFAULT_STOCK_SLIPPAGE_CONFIG, config)
    if not isinstance(trade, dict):
        return {"ok": False, "asset_type": "stock", "ticker": "", "error": "Trade must be a dictionary."}

    ticker = _ticker(trade.get("ticker"))
    entry_price = _safe_float(trade.get("entry_price"))
    if entry_price is None or entry_price <= 0:
        return {
            "ok": False,
            "asset_type": "stock",
            "ticker": ticker,
            "liquidity_tier": "unknown",
            "estimated_slippage_percent": None,
            "estimated_slippage_dollars": None,
            "market_impact_percent": None,
            "spread_cost_percent": None,
            "warnings": [],
            "error": "entry_price is required for stock slippage estimation.",
        }

    tier_result = classify_liquidity_tier(trade, market_snapshot)
    tier = tier_result.get("liquidity_tier", "unknown")
    base_percent = cfg.get(f"{tier}_slippage_percent", cfg["unknown_slippage_percent"])

    data = _market_data(market_snapshot)
    quote = data.get("quote") if isinstance(data.get("quote"), dict) else {}
    bid = _safe_float(quote.get("bid"))
    ask = _safe_float(quote.get("ask"))
    spread_cost_percent = 0.0
    if bid is not None and ask is not None and bid > 0 and ask >= bid:
        spread_cost_percent = ((ask - bid) / ((bid + ask) / 2.0)) * 100.0

    impact = estimate_market_impact(trade, trade.get("position_sizing") if isinstance(trade.get("position_sizing"), dict) else None, market_snapshot)
    market_impact_percent = _safe_float(impact.get("market_impact_percent")) or 0.0
    total_percent = base_percent + market_impact_percent + (spread_cost_percent / 2.0)

    warnings = []
    warnings.extend(tier_result.get("warnings", []))
    warnings.extend(impact.get("warnings", []))
    if tier in {"low_liquidity", "unknown"}:
        warnings.append("Liquidity is limited or unknown; paper fill may be optimistic.")

    return {
        "ok": True,
        "asset_type": "stock",
        "ticker": ticker,
        "liquidity_tier": tier,
        "estimated_slippage_percent": round(total_percent, 4),
        "estimated_slippage_dollars": round(entry_price * (total_percent / 100.0), 4),
        "market_impact_percent": round(market_impact_percent, 4),
        "spread_cost_percent": round(spread_cost_percent, 4),
        "warnings": warnings,
        "error": None,
    }


def estimate_option_slippage(
    trade: dict,
    option_quote: dict | None = None,
    config: dict | None = None,
) -> dict:
    cfg = _merge_config(DEFAULT_OPTION_SLIPPAGE_CONFIG, config)
    quote = option_quote if isinstance(option_quote, dict) else trade if isinstance(trade, dict) else {}
    ticker = _ticker((trade or {}).get("underlying_ticker") or (trade or {}).get("ticker"))
    option_contract = quote.get("option_contract") or (trade or {}).get("option_contract")
    bid = _safe_float(quote.get("bid"))
    ask = _safe_float(quote.get("ask"))

    if bid is None or ask is None or bid < 0 or ask <= 0 or ask < bid:
        return {
            "ok": False,
            "asset_type": "option",
            "ticker": ticker,
            "option_contract": option_contract,
            "bid": bid,
            "ask": ask,
            "mid": None,
            "spread": None,
            "spread_percent": None,
            "estimated_fill_price": None,
            "fill_quality": "unavailable",
            "warnings": [],
            "error": "Option bid/ask quotes are required for paper fill estimation.",
        }

    mid = (bid + ask) / 2.0
    spread = ask - bid
    spread_percent = spread / mid if mid else None
    warnings: list[str] = []
    if spread_percent is None:
        fill_quality = "unavailable"
        fraction = None
    elif spread_percent <= cfg["tight_spread_threshold"]:
        fill_quality = "good"
        fraction = cfg["tight_spread_fraction"]
    elif spread_percent <= cfg["normal_spread_threshold"]:
        fill_quality = "usable"
        fraction = cfg["normal_spread_fraction"]
    elif spread_percent <= cfg["wide_spread_threshold"]:
        fill_quality = "poor"
        fraction = cfg["wide_spread_fraction"]
        warnings.append("Option spread is wide; paper fill quality is poor.")
    else:
        fill_quality = "poor"
        fraction = None
        warnings.append("Option spread is very wide; final option recommendations should be blocked.")

    estimated_fill_price = round(mid + (spread * fraction), 4) if fraction is not None else None

    return {
        "ok": estimated_fill_price is not None,
        "asset_type": "option",
        "ticker": ticker,
        "option_contract": option_contract,
        "bid": bid,
        "ask": ask,
        "mid": round(mid, 4),
        "spread": round(spread, 4),
        "spread_percent": round(spread_percent, 4) if spread_percent is not None else None,
        "estimated_fill_price": estimated_fill_price,
        "fill_quality": fill_quality,
        "warnings": warnings,
        "error": None if estimated_fill_price is not None else "Option spread is too wide for a reliable simulated fill.",
    }

