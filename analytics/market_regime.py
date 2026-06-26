from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeoutError
from copy import deepcopy
from datetime import datetime, timezone
import os
import time
from typing import Any

from realtime.market_data import get_market_snapshot
from providers.market_data_provider import is_ibkr_market_data_provider
from scanner.universe_builder import get_default_universe


DEFAULT_MARKET_REGIME_TIMEOUT_SECONDS = 10.0
DEFAULT_MARKET_REGIME_BREADTH_TIMEOUT_SECONDS = 8.0
DEFAULT_BREADTH_SAMPLE_SIZE = 5
MARKET_REGIME_TIMEOUT_WARNING = "Market regime context timed out; using candidate-level data only."


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _safe_float(value: Any) -> float | None:
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _env_float(name: str, default: float, minimum: float = 0.01, maximum: float = 120.0) -> float:
    try:
        value = float(os.getenv(name, default))
    except (TypeError, ValueError):
        value = default
    return max(minimum, min(value, maximum))


def _env_int(name: str, default: int, minimum: int = 0, maximum: int = 100) -> int:
    try:
        value = int(os.getenv(name, default))
    except (TypeError, ValueError):
        value = default
    return max(minimum, min(value, maximum))


def _timeout_seconds(value: float | None, env_name: str, default: float) -> float:
    if value is not None:
        try:
            return max(0.01, min(float(value), 120.0))
        except (TypeError, ValueError):
            pass
    return _env_float(env_name, default)


def _breadth_sample_size(value: int | None = None) -> int:
    if value is not None:
        try:
            return max(0, min(int(value), 100))
        except (TypeError, ValueError):
            pass
    return _env_int("MARKET_REGIME_BREADTH_SAMPLE_SIZE", DEFAULT_BREADTH_SAMPLE_SIZE, minimum=0, maximum=100)


def _remaining(deadline: float) -> float:
    return max(0.0, deadline - time.monotonic())


def _timeout_snapshot(ticker: str, error: str) -> dict:
    return {
        "ok": False,
        "ticker": ticker,
        "source": "unavailable",
        "timestamp": _now_iso(),
        "data": None,
        "error": error,
        "warning": error,
        "error_type": "timeout",
    }


def _get_market_snapshot_bounded(ticker: str, lookback_days: int, timeout_seconds: float) -> dict:
    if timeout_seconds <= 0:
        return _timeout_snapshot(ticker, f"{ticker} market-regime snapshot timed out before it could start.")
    executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix=f"market-regime-{ticker.lower()}")
    future = executor.submit(get_market_snapshot, ticker, lookback_days=lookback_days)
    try:
        result = future.result(timeout=timeout_seconds)
        return result if isinstance(result, dict) else _timeout_snapshot(ticker, f"{ticker} market-regime snapshot returned malformed data.")
    except FutureTimeoutError:
        return _timeout_snapshot(ticker, f"{ticker} market-regime snapshot timed out after {round(timeout_seconds, 2)} seconds.")
    except Exception as exc:
        return _timeout_snapshot(ticker, f"{ticker} market-regime snapshot failed: {exc}")
    finally:
        executor.shutdown(wait=False, cancel_futures=True)


def _snapshot_technical(snapshot: dict | None) -> dict:
    if not isinstance(snapshot, dict):
        return {}
    data = snapshot.get("data", {})
    if isinstance(data, dict):
        technical = data.get("technical_snapshot", {})
        if isinstance(technical, dict):
            return technical
    technical = snapshot.get("technical_snapshot", {})
    return technical if isinstance(technical, dict) else {}


def _current_price(snapshot: dict | None) -> float | None:
    technical = _snapshot_technical(snapshot)
    price = _safe_float(technical.get("current_price"))
    if price is not None:
        return price
    if isinstance(snapshot, dict):
        data = snapshot.get("data", {})
        if isinstance(data, dict):
            quote = data.get("quote", {})
            if isinstance(quote, dict):
                return _safe_float(quote.get("last_price"))
    return None


def _dedupe(values: list[Any]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        item = str(value or "").strip()
        key = item.lower()
        if not item or key in seen:
            continue
        seen.add(key)
        result.append(item)
    return result


def _snapshot_warning(snapshot: dict | None, label: str) -> str | None:
    if not isinstance(snapshot, dict) or snapshot.get("ok"):
        return None
    error = snapshot.get("error")
    if not error:
        return None
    return f"{label} market-regime snapshot unavailable: {error}"


def _vix_unavailable_snapshot(error: str) -> dict:
    return {
        "ok": False,
        "ticker": "VIX",
        "source": "unavailable",
        "timestamp": _now_iso(),
        "data": {
            "volatility_fallback": "SPY_ATR",
        },
        "error": error,
        "warning": "VIX unavailable; using SPY ATR volatility context when available.",
    }


def _get_optional_vix_snapshot(timeout_seconds: float | None = None) -> dict:
    if is_ibkr_market_data_provider():
        return _vix_unavailable_snapshot(
            "IBKR VIX stock-contract lookup skipped. VIX is an index, not a SMART-routed stock."
        )
    try:
        timeout = timeout_seconds if timeout_seconds is not None else DEFAULT_MARKET_REGIME_TIMEOUT_SECONDS
        return _get_market_snapshot_bounded("I:VIX", lookback_days=120, timeout_seconds=timeout)
    except Exception as exc:
        return _vix_unavailable_snapshot(f"VIX snapshot request failed: {exc}")


def analyze_index_trend(
    ticker: str,
    market_snapshot: dict,
) -> dict:
    technical = _snapshot_technical(market_snapshot)
    current_price = _safe_float(technical.get("current_price"))
    sma_20 = _safe_float(technical.get("sma_20"))
    sma_50 = _safe_float(technical.get("sma_50"))
    sma_200 = _safe_float(technical.get("sma_200"))
    distance_from_20_sma = _safe_float(technical.get("distance_from_20_sma"))
    distance_from_50_sma = _safe_float(technical.get("distance_from_50_sma"))
    atr_percent = _safe_float(technical.get("atr_percent"))

    if current_price is None:
        return {
            "ok": False,
            "ticker": ticker.upper(),
            "trend": "unknown",
            "extended": False,
            "current_price": None,
            "sma_20": sma_20,
            "sma_50": sma_50,
            "sma_200": sma_200,
            "distance_from_20_sma": distance_from_20_sma,
            "distance_from_50_sma": distance_from_50_sma,
            "atr_percent": atr_percent,
            "error": "Current price is unavailable.",
        }

    above_20 = sma_20 is not None and current_price > sma_20
    above_50 = sma_50 is not None and current_price > sma_50
    above_200 = sma_200 is not None and current_price > sma_200
    below_50 = sma_50 is not None and current_price < sma_50
    below_200 = sma_200 is not None and current_price < sma_200

    extended = False
    if distance_from_20_sma is not None and distance_from_20_sma >= 6.0:
        extended = True
    if atr_percent is not None and atr_percent >= 4.5 and (distance_from_20_sma or 0.0) > 4.0:
        extended = True

    if above_20 and above_50 and above_200:
        trend = "bullish"
    elif above_50 and above_200:
        trend = "constructive"
    elif below_50 and below_200:
        trend = "bearish"
    else:
        trend = "mixed"

    return {
        "ok": True,
        "ticker": ticker.upper(),
        "trend": trend,
        "extended": extended,
        "current_price": current_price,
        "sma_20": sma_20,
        "sma_50": sma_50,
        "sma_200": sma_200,
        "distance_from_20_sma": distance_from_20_sma,
        "distance_from_50_sma": distance_from_50_sma,
        "atr_percent": atr_percent,
        "error": None,
    }


def analyze_volatility_regime(
    vix_snapshot: dict | None = None,
    spy_snapshot: dict | None = None,
) -> dict:
    vix_value = _current_price(vix_snapshot)
    if vix_value is not None:
        if vix_value < 16:
            label = "low"
        elif vix_value <= 22:
            label = "normal"
        elif vix_value <= 30:
            label = "elevated"
        else:
            label = "high"
        return {
            "ok": True,
            "source": "VIX",
            "volatility_label": label,
            "vix_value": vix_value,
            "spy_atr_percent": _safe_float(_snapshot_technical(spy_snapshot).get("atr_percent")),
            "error": None,
            "warnings": [],
        }

    spy_atr_percent = _safe_float(_snapshot_technical(spy_snapshot).get("atr_percent"))
    if spy_atr_percent is None:
        return {
            "ok": False,
            "source": "unknown",
            "volatility_label": "unknown",
            "vix_value": None,
            "spy_atr_percent": None,
            "error": "VIX and SPY ATR context are unavailable.",
            "warnings": [_snapshot_warning(vix_snapshot, "VIX")] if _snapshot_warning(vix_snapshot, "VIX") else [],
        }

    if spy_atr_percent < 1.5:
        label = "low"
    elif spy_atr_percent <= 2.5:
        label = "normal"
    elif spy_atr_percent <= 4.0:
        label = "elevated"
    else:
        label = "high"

    return {
        "ok": True,
        "source": "SPY_ATR",
        "volatility_label": label,
        "vix_value": None,
        "spy_atr_percent": spy_atr_percent,
        "error": None,
        "warnings": _dedupe(
            [
                "VIX unavailable; using SPY ATR volatility context.",
                _snapshot_warning(vix_snapshot, "VIX"),
            ]
        ),
    }


def analyze_market_breadth(
    universe_snapshots: list[dict] | None = None,
) -> dict:
    if not isinstance(universe_snapshots, list) or not universe_snapshots:
        return {
            "ok": True,
            "sample_size": 0,
            "percent_above_sma_20": None,
            "percent_above_sma_50": None,
            "percent_positive_daily_return": None,
            "percent_relative_volume_1_2": None,
            "breadth_label": "unknown",
            "error": None,
        }

    valid_count = 0
    above_20 = 0
    above_50 = 0
    positive_daily = 0
    elevated_rvol = 0

    for snapshot in universe_snapshots:
        technical = _snapshot_technical(snapshot)
        current_price = _safe_float(technical.get("current_price"))
        sma_20 = _safe_float(technical.get("sma_20"))
        sma_50 = _safe_float(technical.get("sma_50"))
        daily_return = _safe_float(technical.get("daily_return"))
        relative_volume = _safe_float(technical.get("relative_volume"))

        if current_price is None:
            continue
        valid_count += 1
        if sma_20 is not None and current_price > sma_20:
            above_20 += 1
        if sma_50 is not None and current_price > sma_50:
            above_50 += 1
        if daily_return is not None and daily_return > 0:
            positive_daily += 1
        if relative_volume is not None and relative_volume >= 1.2:
            elevated_rvol += 1

    if valid_count == 0:
        return {
            "ok": True,
            "sample_size": 0,
            "percent_above_sma_20": None,
            "percent_above_sma_50": None,
            "percent_positive_daily_return": None,
            "percent_relative_volume_1_2": None,
            "breadth_label": "unknown",
            "error": None,
        }

    percent_above_sma_20 = round((above_20 / valid_count) * 100.0, 2)
    percent_above_sma_50 = round((above_50 / valid_count) * 100.0, 2)
    percent_positive_daily_return = round((positive_daily / valid_count) * 100.0, 2)
    percent_relative_volume_1_2 = round((elevated_rvol / valid_count) * 100.0, 2)

    if percent_above_sma_20 >= 70 and percent_above_sma_50 >= 65:
        breadth_label = "strong"
    elif percent_above_sma_20 >= 55 and percent_above_sma_50 >= 50:
        breadth_label = "healthy"
    elif percent_above_sma_20 < 35 and percent_above_sma_50 < 35:
        breadth_label = "weak"
    else:
        breadth_label = "mixed"

    return {
        "ok": True,
        "sample_size": valid_count,
        "percent_above_sma_20": percent_above_sma_20,
        "percent_above_sma_50": percent_above_sma_50,
        "percent_positive_daily_return": percent_positive_daily_return,
        "percent_relative_volume_1_2": percent_relative_volume_1_2,
        "breadth_label": breadth_label,
        "error": None,
    }


def determine_market_regime(
    spy_snapshot: dict | None = None,
    qqq_snapshot: dict | None = None,
    iwm_snapshot: dict | None = None,
    vix_snapshot: dict | None = None,
    universe_snapshots: list[dict] | None = None,
) -> dict:
    timestamp = _now_iso()
    spy_context = analyze_index_trend("SPY", spy_snapshot or {})
    qqq_context = analyze_index_trend("QQQ", qqq_snapshot or {})
    iwm_context = analyze_index_trend("IWM", iwm_snapshot or {})
    vix_context = analyze_volatility_regime(vix_snapshot=vix_snapshot, spy_snapshot=spy_snapshot)
    breadth_context = analyze_market_breadth(universe_snapshots=universe_snapshots)
    input_warnings = _dedupe(
        [
            _snapshot_warning(spy_snapshot, "SPY"),
            _snapshot_warning(qqq_snapshot, "QQQ"),
            _snapshot_warning(iwm_snapshot, "IWM"),
            *list(vix_context.get("warnings", []) if isinstance(vix_context.get("warnings"), list) else []),
        ]
    )

    index_context = {
        "SPY": spy_context,
        "QQQ": qqq_context,
        "IWM": iwm_context,
        "VIX": vix_context,
    }

    valid_indexes = [context for context in (spy_context, qqq_context, iwm_context) if context.get("ok")]
    if not valid_indexes and not vix_context.get("ok"):
        return {
            "ok": True,
            "timestamp": timestamp,
            "regime": "unknown",
            "risk_level": "medium",
            "confidence": 0.0,
            "confidence_label": "low",
            "trade_aggressiveness": "defensive",
            "stock_risk_multiplier": 0.5,
            "option_risk_multiplier": 0.0,
            "allowed_setups": ["watchlist_only"],
            "blocked_setups": ["all_final_recommendations"],
            "max_trades_adjustment": 0,
            "long_bias": False,
            "short_bias": False,
            "options_aggressiveness": "normal",
            "index_context": index_context,
            "breadth_context": breadth_context,
            "risk_flags": ["Insufficient market data for regime analysis."],
            "warnings": _dedupe(["Insufficient market data for regime analysis.", *input_warnings]),
            "reasons": ["Index and volatility context are unavailable."],
            "data_quality": {"quality_label": "poor"},
            "summary": "Market regime is unknown because index and volatility context are unavailable.",
        }

    bullish_count = sum(1 for context in valid_indexes if context.get("trend") == "bullish")
    constructive_count = sum(1 for context in valid_indexes if context.get("trend") == "constructive")
    bearish_count = sum(1 for context in valid_indexes if context.get("trend") == "bearish")
    mixed_count = sum(1 for context in valid_indexes if context.get("trend") == "mixed")
    extended_count = sum(1 for context in valid_indexes if context.get("extended"))
    volatility_label = vix_context.get("volatility_label", "unknown")
    breadth_label = breadth_context.get("breadth_label", "unknown")

    regime = "neutral_range"
    if volatility_label == "high":
        regime = "high_volatility_risk_off"
    elif bearish_count >= 2 and volatility_label in {"elevated", "high"}:
        regime = "liquidity_stress"
    elif bearish_count >= 2:
        regime = "bear_trend"
    elif bullish_count >= 2 and breadth_label in {"strong", "healthy"} and volatility_label in {"low", "normal"} and extended_count == 0:
        regime = "strong_bull_trend"
    elif bullish_count >= 2 and (extended_count >= 1 or breadth_label in {"mixed", "unknown"}):
        regime = "weak_bull_chop"
    elif mixed_count >= 1 and breadth_label == "weak":
        regime = "distribution_warning"
    elif bullish_count == 0 and bearish_count == 0 and constructive_count >= 2:
        regime = "neutral_range"

    risk_flags: list[str] = []
    if volatility_label == "elevated":
        risk_flags.append("Volatility is elevated.")
    if volatility_label == "high":
        risk_flags.append("Volatility is high. Reduce aggressiveness.")
    if extended_count >= 2:
        risk_flags.append("Major indexes are extended above short-term trend.")
    if breadth_label == "weak":
        risk_flags.append("Market breadth is weak.")
    elif breadth_label == "mixed":
        risk_flags.append("Market breadth is mixed.")
    if bearish_count >= 2:
        risk_flags.append("Multiple major indexes are below key moving averages.")

    if regime == "strong_bull_trend":
        confidence_label = "high" if breadth_label in {"healthy", "strong"} else "medium"
        confidence = 0.9 if confidence_label == "high" else 0.75
        risk_level = "low"
        trade_aggressiveness = "aggressive" if volatility_label == "low" and breadth_label == "strong" else "normal"
        stock_risk_multiplier = 1.0
        option_risk_multiplier = 1.0
        max_trades_adjustment = 1
        long_bias = True
        short_bias = False
        options_aggressiveness = "aggressive" if volatility_label == "low" else "normal"
        allowed_setups = ["momentum_breakout", "trend_pullback", "relative_strength"]
        blocked_setups = []
    elif regime == "weak_bull_chop":
        confidence_label = "medium"
        confidence = 0.65
        risk_level = "medium"
        trade_aggressiveness = "conservative"
        stock_risk_multiplier = 0.75
        option_risk_multiplier = 0.5
        max_trades_adjustment = -1
        long_bias = True
        short_bias = False
        options_aggressiveness = "conservative"
        allowed_setups = ["trend_pullback", "relative_strength"]
        blocked_setups = ["low_quality_breakout"]
    elif regime == "neutral_range":
        confidence_label = "medium" if valid_indexes else "low"
        confidence = 0.55 if valid_indexes else 0.35
        risk_level = "medium"
        trade_aggressiveness = "conservative"
        stock_risk_multiplier = 0.65
        option_risk_multiplier = 0.25
        max_trades_adjustment = -2
        long_bias = False
        short_bias = False
        options_aggressiveness = "conservative"
        allowed_setups = ["oversold_reversal", "catalyst_watch"]
        blocked_setups = ["momentum_breakout"]
    elif regime == "distribution_warning":
        confidence_label = "medium"
        confidence = 0.65
        risk_level = "high"
        trade_aggressiveness = "defensive"
        stock_risk_multiplier = 0.5
        option_risk_multiplier = 0.0
        max_trades_adjustment = -3
        long_bias = False
        short_bias = False
        options_aggressiveness = "avoid"
        allowed_setups = ["watchlist_only"]
        blocked_setups = ["momentum_breakout", "relative_strength"]
    elif regime == "bear_trend":
        confidence_label = "high" if bearish_count >= 3 else "medium"
        confidence = 0.85 if bearish_count >= 3 else 0.7
        risk_level = "high"
        trade_aggressiveness = "defensive"
        stock_risk_multiplier = 0.35
        option_risk_multiplier = 0.0
        max_trades_adjustment = -5
        long_bias = False
        short_bias = True
        options_aggressiveness = "avoid"
        allowed_setups = ["watchlist_only"]
        blocked_setups = ["momentum_breakout", "trend_pullback", "relative_strength"]
    elif regime == "high_volatility_risk_off":
        confidence_label = "high"
        confidence = 0.9
        risk_level = "critical"
        trade_aggressiveness = "blocked"
        stock_risk_multiplier = 0.0
        option_risk_multiplier = 0.0
        max_trades_adjustment = -5
        long_bias = False
        short_bias = False
        options_aggressiveness = "avoid"
        allowed_setups = []
        blocked_setups = ["all_final_recommendations"]
    elif regime == "liquidity_stress":
        confidence_label = "high"
        confidence = 0.9
        risk_level = "critical"
        trade_aggressiveness = "blocked"
        stock_risk_multiplier = 0.0
        option_risk_multiplier = 0.0
        max_trades_adjustment = -5
        long_bias = False
        short_bias = False
        options_aggressiveness = "avoid"
        allowed_setups = []
        blocked_setups = ["all_final_recommendations"]
    elif regime == "mixed":
        confidence_label = "low" if breadth_label == "unknown" else "medium"
        confidence = 0.45
        risk_level = "medium"
        trade_aggressiveness = "conservative"
        stock_risk_multiplier = 0.65
        option_risk_multiplier = 0.25
        max_trades_adjustment = -1
        long_bias = False
        short_bias = False
        options_aggressiveness = "conservative"
        allowed_setups = ["trend_pullback", "catalyst_watch"]
        blocked_setups = ["low_quality_breakout"]
    else:
        confidence_label = "low"
        confidence = 0.35
        risk_level = "medium"
        trade_aggressiveness = "defensive"
        stock_risk_multiplier = 0.5
        option_risk_multiplier = 0.0
        max_trades_adjustment = 0
        long_bias = False
        short_bias = False
        options_aggressiveness = "normal"
        allowed_setups = ["watchlist_only"]
        blocked_setups = ["unknown_quality_setups"]

    summary = (
        f"Market regime is {regime.replace('_', ' ')} with {confidence_label} confidence. "
        f"Volatility is {volatility_label}, breadth is {breadth_label}, and trade aggressiveness is {trade_aggressiveness}."
    )

    return {
        "ok": True,
        "timestamp": timestamp,
        "regime": regime,
        "risk_level": risk_level,
        "confidence": confidence,
        "confidence_label": confidence_label,
        "trade_aggressiveness": trade_aggressiveness,
        "stock_risk_multiplier": stock_risk_multiplier,
        "option_risk_multiplier": option_risk_multiplier,
        "allowed_setups": allowed_setups,
        "blocked_setups": blocked_setups,
        "max_trades_adjustment": max_trades_adjustment,
        "long_bias": long_bias,
        "short_bias": short_bias,
        "options_aggressiveness": options_aggressiveness,
        "index_context": index_context,
        "breadth_context": breadth_context,
        "risk_flags": risk_flags,
        "warnings": _dedupe([*risk_flags, *input_warnings]),
        "reasons": [
            f"bullish_indexes={bullish_count}",
            f"bearish_indexes={bearish_count}",
            f"volatility={volatility_label}",
            f"breadth={breadth_label}",
        ],
        "data_quality": {"quality_label": "usable" if valid_indexes else "poor"},
        "summary": summary,
    }


def get_market_regime_snapshot(
    include_breadth: bool = False,
    db_path: str = "strategy_library.db",
    timeout_seconds: float | None = None,
    breadth_timeout_seconds: float | None = None,
    breadth_sample_size: int | None = None,
) -> dict:
    del db_path

    total_timeout = _timeout_seconds(timeout_seconds, "MARKET_REGIME_TIMEOUT_SECONDS", DEFAULT_MARKET_REGIME_TIMEOUT_SECONDS)
    breadth_timeout = _timeout_seconds(
        breadth_timeout_seconds,
        "MARKET_REGIME_BREADTH_TIMEOUT_SECONDS",
        DEFAULT_MARKET_REGIME_BREADTH_TIMEOUT_SECONDS,
    )
    sample_size = _breadth_sample_size(breadth_sample_size)
    deadline = time.monotonic() + total_timeout
    warnings: list[str] = []

    spy_snapshot = _get_market_snapshot_bounded("SPY", lookback_days=250, timeout_seconds=_remaining(deadline))
    qqq_snapshot = _get_market_snapshot_bounded("QQQ", lookback_days=250, timeout_seconds=_remaining(deadline))
    iwm_snapshot = _get_market_snapshot_bounded("IWM", lookback_days=250, timeout_seconds=_remaining(deadline))
    vix_snapshot = _get_optional_vix_snapshot(timeout_seconds=_remaining(deadline))
    for snapshot in (spy_snapshot, qqq_snapshot, iwm_snapshot, vix_snapshot):
        warning = snapshot.get("warning") if isinstance(snapshot, dict) else None
        if warning:
            warnings.append(str(warning))

    breadth_snapshots: list[dict] | None = None
    breadth_deadline = min(deadline, time.monotonic() + breadth_timeout)
    breadth_timed_out = False
    if include_breadth and sample_size > 0 and _remaining(deadline) > 0:
        universe_result = get_default_universe(universe="large_cap", max_tickers=sample_size)
        if isinstance(universe_result, dict) and universe_result.get("ok"):
            breadth_snapshots = []
            for ticker in universe_result.get("tickers", [])[:sample_size]:
                remaining = min(_remaining(deadline), _remaining(breadth_deadline))
                if remaining <= 0:
                    breadth_timed_out = True
                    break
                snapshot = _get_market_snapshot_bounded(ticker, lookback_days=120, timeout_seconds=remaining)
                if isinstance(snapshot, dict):
                    breadth_snapshots.append(snapshot)
                    if snapshot.get("warning"):
                        warnings.append(str(snapshot["warning"]))
        if breadth_timed_out:
            warnings.append("Market breadth context timed out; continuing with index-only regime context.")
    elif include_breadth and sample_size <= 0:
        warnings.append("Market breadth context skipped because MARKET_REGIME_BREADTH_SAMPLE_SIZE is 0.")

    regime_result = determine_market_regime(
        spy_snapshot=spy_snapshot if spy_snapshot.get("ok") else None,
        qqq_snapshot=qqq_snapshot if qqq_snapshot.get("ok") else None,
        iwm_snapshot=iwm_snapshot if iwm_snapshot.get("ok") else None,
        vix_snapshot=vix_snapshot,
        universe_snapshots=breadth_snapshots,
    )
    regime_result["include_breadth"] = include_breadth
    regime_result["breadth_sample_size_requested"] = sample_size if include_breadth else 0
    regime_result["breadth_timed_out"] = breadth_timed_out
    regime_result["timeout_seconds"] = total_timeout
    regime_result["breadth_timeout_seconds"] = breadth_timeout
    regime_result["snapshots_requested"] = ["SPY", "QQQ", "IWM", "VIX"]
    regime_result["snapshot_status"] = {
        "SPY": "available" if spy_snapshot.get("ok") else "unavailable",
        "QQQ": "available" if qqq_snapshot.get("ok") else "unavailable",
        "IWM": "available" if iwm_snapshot.get("ok") else "unavailable",
        "VIX": "available" if vix_snapshot.get("ok") else "fallback",
    }
    if _remaining(deadline) <= 0:
        warnings.append(MARKET_REGIME_TIMEOUT_WARNING)
        regime_result["timed_out"] = True
    else:
        regime_result["timed_out"] = bool(breadth_timed_out)
    if warnings:
        regime_result["warnings"] = _dedupe(list(regime_result.get("warnings", [])) + warnings)
    return regime_result


def apply_regime_to_trade_selection(
    selection_result: dict,
    regime_result: dict,
    config: dict | None = None,
) -> dict:
    del config

    adjusted = deepcopy(selection_result) if isinstance(selection_result, dict) else {}
    if not adjusted.get("ok") or not isinstance(regime_result, dict) or not regime_result.get("ok"):
        return adjusted

    selected_trades = adjusted.get("selected_trades", [])
    if not isinstance(selected_trades, list):
        selected_trades = []
    watchlist = adjusted.get("watchlist_alternatives", [])
    if not isinstance(watchlist, list):
        watchlist = []

    regime = str(regime_result.get("regime", "unknown")).lower()
    trade_aggressiveness = str(regime_result.get("trade_aggressiveness", "none")).lower()
    options_aggressiveness = str(regime_result.get("options_aggressiveness", "avoid")).lower()
    risk_flags = [str(flag) for flag in regime_result.get("risk_flags", []) if flag]
    selection_summary = adjusted.get("selection_summary", {})
    if not isinstance(selection_summary, dict):
        selection_summary = {}

    original_selected = list(selection_result.get("selected_trades", [])) if isinstance(selection_result, dict) and isinstance(selection_result.get("selected_trades"), list) else []
    original_max = int(selection_summary.get("max_trades", len(selected_trades) or 0) or 0)
    capped_max = max(0, original_max + int(regime_result.get("max_trades_adjustment", 0) or 0))
    if regime in {"risk_off_downtrend", "high_volatility", "bear_trend", "high_volatility_risk_off", "liquidity_stress", "distribution_warning"}:
        capped_max = min(capped_max, 1)
        if trade_aggressiveness in {"none", "blocked"}:
            capped_max = 0
    elif regime in {"neutral_chop", "neutral_range"}:
        capped_max = min(capped_max, 2) if capped_max > 0 else 0
    elif regime in {"risk_on_extended", "weak_bull_chop"}:
        capped_max = min(capped_max, 3) if capped_max > 0 else 0

    trimmed = selected_trades[capped_max:] if capped_max < len(selected_trades) else []
    selected_trades = selected_trades[:capped_max]

    for trade in selected_trades:
        if not isinstance(trade, dict):
            continue
        trade.setdefault("regime_risk_flags", [])
        if isinstance(trade["regime_risk_flags"], list):
            trade["regime_risk_flags"].extend(risk_flags)
        trade["market_regime"] = regime_result
        trade["options_aggressiveness"] = options_aggressiveness

    for trade in trimmed:
        if not isinstance(trade, dict):
            continue
        trade["regime_removed"] = True
        trade["regime_removed_reason"] = f"Removed by market regime filter: {regime}."
    watchlist = trimmed + watchlist

    adjusted["selected_trades"] = selected_trades
    adjusted["watchlist_alternatives"] = watchlist
    adjusted["market_regime"] = regime_result
    adjusted["regime_adjustment"] = {
        "original_selected_count": len(original_selected),
        "adjusted_selected_count": len(selected_trades),
        "capped_max_trades": capped_max,
        "trade_aggressiveness": trade_aggressiveness,
        "options_aggressiveness": options_aggressiveness,
    }
    selection_summary["selected_count"] = len(selected_trades)
    selection_summary["watchlist_count"] = len(watchlist)
    prior_message = selection_summary.get("message", "")
    selection_summary["message"] = (
        f"{prior_message} Regime filter applied: {regime_result.get('summary')}".strip()
        if prior_message
        else f"Regime filter applied: {regime_result.get('summary')}"
    )
    adjusted["selection_summary"] = selection_summary
    return adjusted
