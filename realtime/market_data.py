from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any
import math

import pandas as pd
import requests

import config
from providers.market_data_provider import is_ibkr_market_data_provider
from quality.data_quality import validate_market_data_quality


SOURCE_NAME = "polygon"
POLYGON_BASE_URL = "https://api.polygon.io"
REQUIRED_OHLCV_COLUMNS = ["open", "high", "low", "close", "volume", "timestamp"]
OHLCV_COLUMN_ALIASES = {
    "timestamp": {"timestamp", "time", "date", "datetime", "t"},
    "open": {"open", "o"},
    "high": {"high", "h"},
    "low": {"low", "l"},
    "close": {"close", "c"},
    "volume": {"volume", "v"},
}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _response(
    ok: bool,
    ticker: str,
    data: Any = None,
    error: str | None = None,
    source: str = SOURCE_NAME,
) -> dict:
    return {
        "ok": ok,
        "ticker": ticker.upper(),
        "source": source,
        "timestamp": _now_iso(),
        "data": data,
        "error": error,
    }


def _get_polygon_api_key() -> str | None:
    return getattr(config, "POLYGON_API_KEY", None)


def _optional_yfinance_available() -> bool:
    try:
        import importlib.util

        return importlib.util.find_spec("yfinance") is not None
    except Exception:
        return False


def _to_iso_timestamp(value: Any) -> str | None:
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return None

    try:
        ts = pd.Timestamp(value)
    except Exception:
        return None

    if ts.tzinfo is None:
        ts = ts.tz_localize("UTC")
    else:
        ts = ts.tz_convert("UTC")
    return ts.isoformat()


def _to_timestamp_series(series: pd.Series) -> pd.Series:
    if pd.api.types.is_numeric_dtype(series):
        numeric_series = pd.to_numeric(series, errors="coerce")
        valid = numeric_series.dropna()
        if valid.empty:
            return pd.to_datetime(series, errors="coerce", utc=True)

        # Polygon aggregate timestamps are milliseconds since epoch.
        unit = "ms" if valid.abs().max() > 10_000_000_000 else "s"
        return pd.to_datetime(numeric_series, unit=unit, errors="coerce", utc=True)

    return pd.to_datetime(series, errors="coerce", utc=True)


def _safe_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    if math.isnan(numeric):
        return None
    return numeric


def _latest_value(series: pd.Series, window: int | None = None) -> float | None:
    subset = series.tail(window) if window else series
    subset = subset.dropna()
    if subset.empty:
        return None
    return _safe_float(subset.iloc[-1])


def _rolling_mean(series: pd.Series, window: int) -> float | None:
    if len(series) < window:
        return None
    return _safe_float(series.rolling(window=window).mean().iloc[-1])


def _rolling_extreme(series: pd.Series, window: int, fn: str) -> float | None:
    if len(series) < window:
        return None
    rolling = getattr(series.rolling(window=window), fn)()
    return _safe_float(rolling.iloc[-1])


def _calculate_rsi(close: pd.Series, window: int = 14) -> float | None:
    if len(close) < window + 1:
        return None

    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.rolling(window=window, min_periods=window).mean()
    avg_loss = loss.rolling(window=window, min_periods=window).mean()

    latest_gain = avg_gain.iloc[-1]
    latest_loss = avg_loss.iloc[-1]

    if pd.isna(latest_gain) or pd.isna(latest_loss):
        return None
    if latest_loss == 0:
        return 100.0

    rs = latest_gain / latest_loss
    return _safe_float(100 - (100 / (1 + rs)))


def _calculate_macd(close: pd.Series) -> float | None:
    if len(close) < 12:
        return None

    fast = close.ewm(span=12, adjust=False).mean()
    slow = close.ewm(span=26, adjust=False).mean()
    macd = fast - slow
    return _safe_float(macd.iloc[-1])


def _calculate_atr(df: pd.DataFrame, window: int = 14) -> float | None:
    if len(df) < window + 1:
        return None

    prev_close = df["close"].shift(1)
    true_range = pd.concat(
        [
            df["high"] - df["low"],
            (df["high"] - prev_close).abs(),
            (df["low"] - prev_close).abs(),
        ],
        axis=1,
    ).max(axis=1)

    atr = true_range.rolling(window=window, min_periods=window).mean()
    return _safe_float(atr.iloc[-1])


def _serialize_bars(df: pd.DataFrame) -> list[dict]:
    serialized = df.copy()
    serialized["timestamp"] = serialized["timestamp"].apply(_to_iso_timestamp)
    return serialized.to_dict(orient="records")


def _extract_snapshot_price(payload: dict) -> tuple[float | None, float | None, float | None, float | None]:
    ticker_data = payload.get("ticker", {}) if isinstance(payload, dict) else {}
    last_trade = ticker_data.get("lastTrade", {}) or {}
    min_data = ticker_data.get("min", {}) or {}
    prev_day = ticker_data.get("prevDay", {}) or {}
    day_data = ticker_data.get("day", {}) or {}

    last_price = _safe_float(last_trade.get("p"))
    if last_price is None:
        last_price = _safe_float(min_data.get("c"))
    previous_close = _safe_float(prev_day.get("c"))
    day_volume = _safe_float(day_data.get("v"))
    last_trade_timestamp = _safe_float(last_trade.get("t"))
    return last_price, previous_close, day_volume, last_trade_timestamp


def _fetch_polygon_aggregates(ticker: str, lookback_days: int, api_key: str) -> pd.DataFrame:
    end = datetime.now(timezone.utc)
    start = end - timedelta(days=lookback_days)
    start_str = start.strftime("%Y-%m-%d")
    end_str = end.strftime("%Y-%m-%d")

    url = (
        f"{POLYGON_BASE_URL}/v2/aggs/ticker/{ticker.upper()}/range/1/day/"
        f"{start_str}/{end_str}?adjusted=true&sort=asc&limit=50000"
    )
    response = requests.get(url, headers={"Authorization": f"Bearer {api_key}"}, timeout=20)
    response.raise_for_status()
    payload = response.json()
    results = payload.get("results", [])
    if not results:
        return pd.DataFrame()
    return pd.DataFrame(results)


def normalize_ohlcv(data: Any) -> pd.DataFrame:
    if data is None:
        return pd.DataFrame(columns=REQUIRED_OHLCV_COLUMNS)

    if isinstance(data, pd.DataFrame):
        df = data.copy()
    elif isinstance(data, dict):
        if "results" in data and isinstance(data["results"], list):
            df = pd.DataFrame(data["results"])
        elif "bars" in data and isinstance(data["bars"], list):
            df = pd.DataFrame(data["bars"])
        else:
            df = pd.DataFrame([data])
    elif isinstance(data, list):
        df = pd.DataFrame(data)
    else:
        return pd.DataFrame(columns=REQUIRED_OHLCV_COLUMNS)

    if df.empty:
        return pd.DataFrame(columns=REQUIRED_OHLCV_COLUMNS)

    renamed_columns = {}
    lower_to_original = {str(column).lower(): column for column in df.columns}
    for canonical_name, aliases in OHLCV_COLUMN_ALIASES.items():
        matching_column = next(
            (lower_to_original[alias] for alias in aliases if alias in lower_to_original),
            None,
        )
        if matching_column is not None:
            renamed_columns[matching_column] = canonical_name

    df = df.rename(columns=renamed_columns)
    if any(column not in df.columns for column in REQUIRED_OHLCV_COLUMNS):
        return pd.DataFrame(columns=REQUIRED_OHLCV_COLUMNS)

    normalized = df[REQUIRED_OHLCV_COLUMNS].copy()
    normalized["timestamp"] = _to_timestamp_series(normalized["timestamp"])

    for column in ["open", "high", "low", "close", "volume"]:
        normalized[column] = pd.to_numeric(normalized[column], errors="coerce")

    normalized = normalized.dropna(subset=["timestamp", "open", "high", "low", "close", "volume"])
    if normalized.empty:
        return pd.DataFrame(columns=REQUIRED_OHLCV_COLUMNS)

    normalized = normalized.sort_values("timestamp").drop_duplicates(subset=["timestamp"], keep="last")
    normalized = normalized.reset_index(drop=True)
    return normalized[REQUIRED_OHLCV_COLUMNS]


def calculate_technical_snapshot(bars_df: pd.DataFrame) -> dict:
    normalized = normalize_ohlcv(bars_df)
    if normalized.empty:
        return {"ok": False, "error": "No valid OHLCV data available for technical calculations."}

    if len(normalized) < 2:
        return {"ok": False, "error": "Not enough OHLCV data to calculate technical snapshot."}

    close = normalized["close"]
    volume = normalized["volume"]

    current_price = _safe_float(close.iloc[-1])
    previous_close = _safe_float(close.iloc[-2]) if len(close) >= 2 else None
    daily_return = None
    if current_price is not None and previous_close not in (None, 0):
        daily_return = ((current_price - previous_close) / previous_close) * 100.0

    sma_20 = _rolling_mean(close, 20)
    sma_50 = _rolling_mean(close, 50)
    sma_200 = _rolling_mean(close, 200)
    average_volume_20 = _rolling_mean(volume, 20)
    relative_volume = None
    if average_volume_20 not in (None, 0) and current_price is not None:
        relative_volume = _safe_float(volume.iloc[-1] / average_volume_20)

    atr_14 = _calculate_atr(normalized, 14)
    atr_percent = None
    if atr_14 is not None and current_price not in (None, 0):
        atr_percent = (atr_14 / current_price) * 100.0

    high_20 = _rolling_extreme(normalized["high"], 20, "max")
    low_20 = _rolling_extreme(normalized["low"], 20, "min")
    distance_from_20_sma = None
    distance_from_50_sma = None
    if sma_20 not in (None, 0) and current_price is not None:
        distance_from_20_sma = ((current_price - sma_20) / sma_20) * 100.0
    if sma_50 not in (None, 0) and current_price is not None:
        distance_from_50_sma = ((current_price - sma_50) / sma_50) * 100.0

    return {
        "ok": True,
        "error": None,
        "current_price": current_price,
        "previous_close": previous_close,
        "daily_return": _safe_float(daily_return),
        "sma_20": sma_20,
        "sma_50": sma_50,
        "sma_200": sma_200,
        "rsi_14": _calculate_rsi(close, 14),
        "macd": _calculate_macd(close),
        "average_volume_20": average_volume_20,
        "relative_volume": relative_volume,
        "atr_14": atr_14,
        "atr_percent": _safe_float(atr_percent),
        "high_20": high_20,
        "low_20": low_20,
        "distance_from_20_sma": _safe_float(distance_from_20_sma),
        "distance_from_50_sma": _safe_float(distance_from_50_sma),
    }


def get_data_freshness(bars_df: pd.DataFrame) -> dict:
    normalized = normalize_ohlcv(bars_df)
    if normalized.empty:
        return {
            "ok": False,
            "error": "No valid OHLCV data available for freshness analysis.",
            "latest_bar_timestamp": None,
            "age_days": None,
            "is_stale": True,
            "freshness_label": "unknown",
        }

    latest_timestamp = pd.Timestamp(normalized["timestamp"].iloc[-1])
    if latest_timestamp.tzinfo is None:
        latest_timestamp = latest_timestamp.tz_localize("UTC")
    else:
        latest_timestamp = latest_timestamp.tz_convert("UTC")

    age_days = (pd.Timestamp.now(tz="UTC") - latest_timestamp).total_seconds() / 86400.0
    age_days = round(age_days, 2)

    if age_days <= 3:
        freshness_label = "fresh"
        is_stale = False
    elif age_days <= 7:
        freshness_label = "slightly_stale"
        is_stale = False
    else:
        freshness_label = "stale"
        is_stale = True

    return {
        "ok": True,
        "error": None,
        "latest_bar_timestamp": latest_timestamp.isoformat(),
        "age_days": age_days,
        "is_stale": is_stale,
        "freshness_label": freshness_label,
    }


def get_live_quote(ticker: str) -> dict:
    if is_ibkr_market_data_provider():
        from providers.ibkr_provider import get_ibkr_live_quote

        return get_ibkr_live_quote(ticker)

    api_key = _get_polygon_api_key()
    if not api_key:
        return _response(False, ticker, error="POLYGON_API_KEY is not configured.")

    url = f"https://api.polygon.io/v2/snapshot/locale/us/markets/stocks/tickers/{ticker.upper()}"
    try:
        response = requests.get(url, headers={"Authorization": f"Bearer {api_key}"}, timeout=15)
        response.raise_for_status()
        payload = response.json()

        if not payload or not payload.get("ticker"):
            return _response(False, ticker, error="Polygon returned an empty snapshot response.")

        last_price, previous_close, day_volume, last_trade_timestamp = _extract_snapshot_price(payload)
        if last_price is None and previous_close is None:
            return _response(False, ticker, error="Polygon snapshot did not include a usable quote.")

        data = {
            "last_price": last_price,
            "previous_close": previous_close,
            "day_volume": day_volume,
            "last_trade_timestamp": _to_iso_timestamp(last_trade_timestamp),
        }
        return _response(True, ticker, data=data)
    except requests.exceptions.RequestException as exc:
        return _response(False, ticker, error=f"Polygon quote request failed: {exc}")
    except Exception as exc:
        return _response(False, ticker, error=f"Unexpected error while fetching live quote: {exc}")


def get_historical_bars(ticker: str, lookback_days: int = 180) -> dict:
    if is_ibkr_market_data_provider():
        from providers.ibkr_provider import get_ibkr_historical_bars

        return get_ibkr_historical_bars(ticker, lookback_days=lookback_days)

    api_key = _get_polygon_api_key()
    if not api_key:
        fallback_note = " Optional yfinance fallback is unavailable." if not _optional_yfinance_available() else ""
        return _response(False, ticker, error=f"POLYGON_API_KEY is not configured.{fallback_note}")

    try:
        raw_bars = _fetch_polygon_aggregates(ticker, lookback_days, api_key)
        normalized = normalize_ohlcv(raw_bars)
        if normalized.empty:
            return _response(False, ticker, error="No historical OHLCV data returned for the requested lookback.")

        data = {
            "bars": _serialize_bars(normalized),
            "row_count": int(len(normalized)),
            "start_timestamp": _to_iso_timestamp(normalized["timestamp"].iloc[0]),
            "end_timestamp": _to_iso_timestamp(normalized["timestamp"].iloc[-1]),
            "schema": REQUIRED_OHLCV_COLUMNS,
        }
        return _response(True, ticker, data=data)
    except ValueError as exc:
        return _response(False, ticker, error=str(exc))
    except Exception as exc:
        return _response(False, ticker, error=f"Unexpected error while fetching historical bars: {exc}")


def get_market_snapshot(ticker: str, lookback_days: int = 180) -> dict:
    if is_ibkr_market_data_provider():
        from providers.ibkr_provider import get_ibkr_market_snapshot

        return get_ibkr_market_snapshot(ticker, lookback_days=lookback_days)

    historical_result = get_historical_bars(ticker, lookback_days=lookback_days)
    if not historical_result["ok"]:
        return historical_result

    bars_df = normalize_ohlcv(historical_result["data"]["bars"])
    technical_snapshot = calculate_technical_snapshot(bars_df)
    freshness = get_data_freshness(bars_df)
    quote_result = get_live_quote(ticker)

    data = {
        "quote": quote_result["data"] if quote_result["ok"] else None,
        "quote_error": quote_result["error"],
        "quote_status": "available" if quote_result["ok"] else "unavailable",
        "quote_fallback_used": False,
        "bars": historical_result["data"]["bars"],
        "row_count": historical_result["data"]["row_count"],
        "technical_snapshot": technical_snapshot,
        "data_freshness": freshness,
        "data_quality_warnings": [],
    }
    response = _response(True, ticker, data=data)
    response["data"]["data_quality"] = validate_market_data_quality(response)
    return response
