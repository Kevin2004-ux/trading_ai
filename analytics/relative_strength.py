from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from typing import Any

from realtime.market_data import get_market_snapshot


SECTOR_ETF_MAP = {
    "technology": "XLK",
    "communication services": "XLC",
    "consumer discretionary": "XLY",
    "financials": "XLF",
    "healthcare": "XLV",
    "industrials": "XLI",
    "energy": "XLE",
    "consumer staples": "XLP",
    "utilities": "XLU",
    "real estate": "XLRE",
    "materials": "XLB",
    "semiconductors": "SOXX",
}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _safe_float(value: Any) -> float | None:
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _normalize_sector(sector: str | None) -> str | None:
    if not sector:
        return None
    normalized = str(sector).strip().lower()
    return normalized or None


def _sector_etf_for(sector: str | None) -> str | None:
    normalized = _normalize_sector(sector)
    if normalized is None:
        return None
    return SECTOR_ETF_MAP.get(normalized)


def _technical(snapshot: dict | None) -> dict:
    if not isinstance(snapshot, dict):
        return {}
    data = snapshot.get("data", {})
    if isinstance(data, dict):
        technical = data.get("technical_snapshot", {})
        if isinstance(technical, dict):
            return technical
    technical = snapshot.get("technical_snapshot", {})
    return technical if isinstance(technical, dict) else {}


def _ticker(snapshot: dict | None, fallback: str = "") -> str:
    if not isinstance(snapshot, dict):
        return fallback
    return str(snapshot.get("ticker") or fallback).upper()


def _above_level(current_price: float | None, level: float | None) -> bool | None:
    if current_price is None or level is None:
        return None
    return current_price > level


def calculate_relative_performance(
    stock_snapshot: dict,
    benchmark_snapshot: dict,
    period_label: str = "current",
) -> dict:
    stock_technical = _technical(stock_snapshot)
    benchmark_technical = _technical(benchmark_snapshot)

    stock_price = _safe_float(stock_technical.get("current_price"))
    benchmark_price = _safe_float(benchmark_technical.get("current_price"))
    stock_daily_return = _safe_float(stock_technical.get("daily_return"))
    benchmark_daily_return = _safe_float(benchmark_technical.get("daily_return"))
    stock_d20 = _safe_float(stock_technical.get("distance_from_20_sma"))
    benchmark_d20 = _safe_float(benchmark_technical.get("distance_from_20_sma"))
    stock_d50 = _safe_float(stock_technical.get("distance_from_50_sma"))
    benchmark_d50 = _safe_float(benchmark_technical.get("distance_from_50_sma"))
    stock_rvol = _safe_float(stock_technical.get("relative_volume"))
    benchmark_rvol = _safe_float(benchmark_technical.get("relative_volume"))
    stock_sma20 = _safe_float(stock_technical.get("sma_20"))
    stock_sma50 = _safe_float(stock_technical.get("sma_50"))
    benchmark_sma20 = _safe_float(benchmark_technical.get("sma_20"))
    benchmark_sma50 = _safe_float(benchmark_technical.get("sma_50"))
    stock_high_20 = _safe_float(stock_technical.get("high_20"))
    benchmark_high_20 = _safe_float(benchmark_technical.get("high_20"))

    if stock_price is None or benchmark_price is None:
        return {
            "ok": False,
            "period_label": period_label,
            "stock_ticker": _ticker(stock_snapshot),
            "benchmark_ticker": _ticker(benchmark_snapshot),
            "comparison_label": "unknown",
            "relative_score": None,
            "daily_return_spread": None,
            "distance_20_spread": None,
            "distance_50_spread": None,
            "relative_volume_spread": None,
            "stock_above_sma_20": None,
            "stock_above_sma_50": None,
            "benchmark_above_sma_20": None,
            "benchmark_above_sma_50": None,
            "breakout_advantage": None,
            "error": "Missing stock or benchmark price context.",
        }

    score = 50.0
    daily_return_spread = None
    if stock_daily_return is not None and benchmark_daily_return is not None:
        daily_return_spread = stock_daily_return - benchmark_daily_return
        score += max(min(daily_return_spread * 6.0, 16.0), -16.0)

    distance_20_spread = None
    if stock_d20 is not None and benchmark_d20 is not None:
        distance_20_spread = stock_d20 - benchmark_d20
        score += max(min(distance_20_spread * 1.2, 8.0), -8.0)

    distance_50_spread = None
    if stock_d50 is not None and benchmark_d50 is not None:
        distance_50_spread = stock_d50 - benchmark_d50
        score += max(min(distance_50_spread * 1.0, 8.0), -8.0)

    relative_volume_spread = None
    if stock_rvol is not None and benchmark_rvol is not None:
        relative_volume_spread = stock_rvol - benchmark_rvol
        score += max(min(relative_volume_spread * 6.0, 8.0), -8.0)
    elif stock_rvol is not None:
        score += max(min((stock_rvol - 1.0) * 4.0, 5.0), -5.0)

    stock_above_sma_20 = _above_level(stock_price, stock_sma20)
    stock_above_sma_50 = _above_level(stock_price, stock_sma50)
    benchmark_above_sma_20 = _above_level(benchmark_price, benchmark_sma20)
    benchmark_above_sma_50 = _above_level(benchmark_price, benchmark_sma50)

    if stock_above_sma_20 is True and benchmark_above_sma_20 is False:
        score += 6.0
    elif stock_above_sma_20 is False and benchmark_above_sma_20 is True:
        score -= 6.0
    if stock_above_sma_50 is True and benchmark_above_sma_50 is False:
        score += 6.0
    elif stock_above_sma_50 is False and benchmark_above_sma_50 is True:
        score -= 6.0

    breakout_advantage = None
    if stock_high_20 is not None and benchmark_high_20 is not None and stock_price and benchmark_price:
        stock_breakout_gap = abs(stock_high_20 - stock_price) / stock_price
        benchmark_breakout_gap = abs(benchmark_high_20 - benchmark_price) / benchmark_price
        breakout_advantage = benchmark_breakout_gap - stock_breakout_gap
        score += max(min(breakout_advantage * 100.0 * 3.0, 6.0), -6.0)

    score = max(0.0, min(100.0, round(score, 2)))
    if score >= 72:
        label = "outperforming"
    elif score <= 32:
        label = "underperforming"
    else:
        label = "neutral"

    return {
        "ok": True,
        "period_label": period_label,
        "stock_ticker": _ticker(stock_snapshot),
        "benchmark_ticker": _ticker(benchmark_snapshot),
        "comparison_label": label,
        "relative_score": score,
        "daily_return_spread": daily_return_spread,
        "distance_20_spread": distance_20_spread,
        "distance_50_spread": distance_50_spread,
        "relative_volume_spread": relative_volume_spread,
        "stock_above_sma_20": stock_above_sma_20,
        "stock_above_sma_50": stock_above_sma_50,
        "benchmark_above_sma_20": benchmark_above_sma_20,
        "benchmark_above_sma_50": benchmark_above_sma_50,
        "breakout_advantage": breakout_advantage,
        "error": None,
    }


def analyze_sector_strength(
    sector_snapshots: dict[str, dict] | None = None,
    spy_snapshot: dict | None = None,
) -> dict:
    if not isinstance(sector_snapshots, dict) or not sector_snapshots:
        return {
            "ok": True,
            "sectors": {},
            "strongest_sector": None,
            "weakest_sector": None,
            "error": None,
        }

    sectors: dict[str, dict] = {}
    for sector_name, snapshot in sector_snapshots.items():
        if not isinstance(snapshot, dict):
            continue
        if spy_snapshot is not None:
            vs_spy = calculate_relative_performance(snapshot, spy_snapshot, period_label="sector_vs_spy")
        else:
            vs_spy = {
                "ok": False,
                "comparison_label": "unknown",
                "relative_score": None,
                "error": "SPY snapshot unavailable.",
            }
        score = _safe_float(vs_spy.get("relative_score"))
        if score is None:
            label = "unknown"
        elif score >= 72:
            label = "outperforming"
        elif score <= 32:
            label = "underperforming"
        else:
            label = "neutral"
        sectors[sector_name] = {
            "ticker": _ticker(snapshot, fallback=sector_name),
            "relative_strength_label": label,
            "relative_strength_score": score,
            "vs_spy": vs_spy,
        }

    sortable = [(name, data) for name, data in sectors.items() if _safe_float(data.get("relative_strength_score")) is not None]
    sortable.sort(key=lambda item: item[1]["relative_strength_score"], reverse=True)
    strongest_sector = sortable[0][0] if sortable else None
    weakest_sector = sortable[-1][0] if sortable else None

    return {
        "ok": True,
        "sectors": sectors,
        "strongest_sector": strongest_sector,
        "weakest_sector": weakest_sector,
        "error": None,
    }


def analyze_stock_relative_strength(
    ticker: str,
    stock_snapshot: dict,
    spy_snapshot: dict | None = None,
    qqq_snapshot: dict | None = None,
    sector_snapshot: dict | None = None,
    sector: str | None = None,
) -> dict:
    timestamp = _now_iso()
    if not isinstance(stock_snapshot, dict) or not stock_snapshot.get("ok"):
        return {
            "ok": False,
            "timestamp": timestamp,
            "ticker": str(ticker or "").upper(),
            "sector": sector,
            "relative_strength_label": "unknown",
            "relative_strength_score": 50.0,
            "vs_spy": None,
            "vs_qqq": None,
            "vs_sector": None,
            "sector_context": {"label": "unknown", "ticker": _sector_etf_for(sector), "relative_strength_score": None},
            "risk_flags": ["Stock snapshot unavailable."],
            "summary": "Relative strength is unknown because stock market data is unavailable.",
            "error": "Stock snapshot unavailable.",
        }

    vs_spy = calculate_relative_performance(stock_snapshot, spy_snapshot, period_label="vs_spy") if isinstance(spy_snapshot, dict) else None
    vs_qqq = calculate_relative_performance(stock_snapshot, qqq_snapshot, period_label="vs_qqq") if isinstance(qqq_snapshot, dict) else None
    vs_sector = calculate_relative_performance(stock_snapshot, sector_snapshot, period_label="vs_sector") if isinstance(sector_snapshot, dict) else None

    scores = [_safe_float(item.get("relative_score")) for item in (vs_spy, vs_qqq, vs_sector) if isinstance(item, dict) and item.get("ok")]
    relative_strength_score = round(sum(scores) / len(scores), 2) if scores else 50.0
    risk_flags: list[str] = []

    stock_technical = _technical(stock_snapshot)
    daily_return = _safe_float(stock_technical.get("daily_return"))
    sma20 = _safe_float(stock_technical.get("sma_20"))
    sma50 = _safe_float(stock_technical.get("sma_50"))
    current_price = _safe_float(stock_technical.get("current_price"))
    if current_price is not None and sma20 is not None and current_price < sma20:
        relative_strength_score -= 6.0
        risk_flags.append("Stock is below its 20-day moving average.")
    if current_price is not None and sma50 is not None and current_price < sma50:
        relative_strength_score -= 8.0
        risk_flags.append("Stock is below its 50-day moving average.")
    if daily_return is not None and daily_return < 0:
        if isinstance(vs_spy, dict) and vs_spy.get("ok") and _safe_float(vs_spy.get("daily_return_spread")) is not None and _safe_float(vs_spy.get("daily_return_spread")) < 0:
            risk_flags.append("Stock is lagging the market on the day.")

    sector_context = {
        "label": "unknown",
        "ticker": _sector_etf_for(sector),
        "relative_strength_score": _safe_float(vs_sector.get("relative_score")) if isinstance(vs_sector, dict) else None,
    }
    if isinstance(vs_sector, dict) and vs_sector.get("ok"):
        sector_context["label"] = str(vs_sector.get("comparison_label", "unknown"))
        if sector_context["label"] == "underperforming":
            relative_strength_score -= 5.0
            risk_flags.append("Stock is weak versus its sector ETF.")
        elif sector_context["label"] == "outperforming":
            relative_strength_score += 4.0

    relative_strength_score = max(0.0, min(100.0, round(relative_strength_score, 2)))
    if not scores:
        label = "unknown"
    elif relative_strength_score >= 82:
        label = "market_leader"
    elif relative_strength_score >= 66:
        label = "outperforming"
    elif relative_strength_score <= 24:
        label = "market_laggard"
    elif relative_strength_score <= 42:
        label = "underperforming"
    else:
        label = "neutral"

    if label in {"underperforming", "market_laggard"}:
        risk_flags.append("Relative strength is weak versus market benchmarks.")

    summary = f"{str(ticker).upper()} is {label.replace('_', ' ')} on relative-strength analysis."

    return {
        "ok": True,
        "timestamp": timestamp,
        "ticker": str(ticker or "").upper(),
        "sector": sector,
        "relative_strength_label": label,
        "relative_strength_score": relative_strength_score,
        "vs_spy": vs_spy,
        "vs_qqq": vs_qqq,
        "vs_sector": vs_sector,
        "sector_context": sector_context,
        "risk_flags": risk_flags,
        "summary": summary,
        "error": None,
    }


def get_relative_strength_snapshot(
    ticker: str,
    sector: str | None = None,
    include_sector: bool = True,
    db_path: str = "strategy_library.db",
) -> dict:
    del db_path
    normalized_ticker = str(ticker or "").upper()
    stock_snapshot = get_market_snapshot(normalized_ticker, lookback_days=180)
    if not stock_snapshot.get("ok"):
        return analyze_stock_relative_strength(
            ticker=normalized_ticker,
            stock_snapshot=stock_snapshot,
            sector=sector,
        )

    spy_snapshot = get_market_snapshot("SPY", lookback_days=180)
    qqq_snapshot = get_market_snapshot("QQQ", lookback_days=180)
    sector_snapshot = None
    sector_etf = _sector_etf_for(sector) if include_sector else None
    if sector_etf:
        fetched_sector_snapshot = get_market_snapshot(sector_etf, lookback_days=180)
        sector_snapshot = fetched_sector_snapshot if fetched_sector_snapshot.get("ok") else None

    return analyze_stock_relative_strength(
        ticker=normalized_ticker,
        stock_snapshot=stock_snapshot,
        spy_snapshot=spy_snapshot if spy_snapshot.get("ok") else None,
        qqq_snapshot=qqq_snapshot if qqq_snapshot.get("ok") else None,
        sector_snapshot=sector_snapshot,
        sector=sector,
    )


def apply_relative_strength_to_candidate(
    candidate: dict,
    relative_strength_result: dict,
    config: dict | None = None,
) -> dict:
    cfg = config or {}
    leader_boost = _safe_float(cfg.get("leader_boost")) or 4.0
    outperforming_boost = _safe_float(cfg.get("outperforming_boost")) or 2.0
    underperforming_penalty = _safe_float(cfg.get("underperforming_penalty")) or 4.0
    laggard_penalty = _safe_float(cfg.get("laggard_penalty")) or 7.0

    enriched = deepcopy(candidate) if isinstance(candidate, dict) else {}
    enriched["relative_strength_context"] = relative_strength_result

    label = str(relative_strength_result.get("relative_strength_label", "unknown")).lower() if isinstance(relative_strength_result, dict) else "unknown"
    adjustment = 0.0
    if label == "market_leader":
        adjustment = leader_boost
    elif label == "outperforming":
        adjustment = outperforming_boost
    elif label == "underperforming":
        adjustment = -underperforming_penalty
    elif label == "market_laggard":
        adjustment = -laggard_penalty

    enriched["relative_strength_adjustment"] = adjustment
    base_score = _safe_float(enriched.get("score"))
    if base_score is not None:
        enriched["score"] = round(max(0.0, min(100.0, base_score + adjustment)), 2)

    risk_flags = []
    if isinstance(relative_strength_result, dict):
        raw_flags = relative_strength_result.get("risk_flags", [])
        if isinstance(raw_flags, list):
            risk_flags = [str(flag) for flag in raw_flags if flag]

    existing_flags = enriched.get("relative_strength_risk_flags", [])
    if not isinstance(existing_flags, list):
        existing_flags = []
    enriched["relative_strength_risk_flags"] = existing_flags + risk_flags
    return enriched
