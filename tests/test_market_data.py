from datetime import timedelta

import pandas as pd

import config
from realtime.market_data import (
    calculate_technical_snapshot,
    get_data_freshness,
    get_historical_bars,
    get_market_snapshot,
    normalize_ohlcv,
)


def _sample_bars(num_rows: int = 250, start_price: float = 100.0) -> pd.DataFrame:
    timestamps = pd.date_range(end=pd.Timestamp.now(tz="UTC"), periods=num_rows, freq="B")
    closes = [start_price + i * 0.5 for i in range(num_rows)]
    opens = [price - 0.25 for price in closes]
    highs = [price + 1.0 for price in closes]
    lows = [price - 1.0 for price in closes]
    volumes = [1_000_000 + i * 1000 for i in range(num_rows)]

    return pd.DataFrame(
        {
            "timestamp": timestamps,
            "open": opens,
            "high": highs,
            "low": lows,
            "close": closes,
            "volume": volumes,
        }
    )


def test_normalize_ohlcv_standardizes_columns():
    raw_df = pd.DataFrame(
        {
            "Date": pd.date_range("2026-01-01", periods=3, freq="D", tz="UTC"),
            "Open": [10, 11, 12],
            "High": [11, 12, 13],
            "Low": [9, 10, 11],
            "Close": [10.5, 11.5, 12.5],
            "Volume": [1000, 1100, 1200],
        }
    )

    normalized = normalize_ohlcv(raw_df)

    assert list(normalized.columns) == ["open", "high", "low", "close", "volume", "timestamp"]
    assert len(normalized) == 3
    assert normalized["timestamp"].dtype.kind == "M"
    assert normalized["close"].iloc[-1] == 12.5


def test_calculate_technical_snapshot_returns_expected_metrics():
    bars_df = _sample_bars()

    snapshot = calculate_technical_snapshot(bars_df)

    assert snapshot["ok"] is True
    assert snapshot["error"] is None
    assert snapshot["current_price"] is not None
    assert snapshot["previous_close"] is not None
    assert snapshot["daily_return"] is not None
    assert snapshot["sma_20"] is not None
    assert snapshot["sma_50"] is not None
    assert snapshot["sma_200"] is not None
    assert snapshot["rsi_14"] is not None
    assert snapshot["macd"] is not None
    assert snapshot["average_volume_20"] is not None
    assert snapshot["relative_volume"] is not None
    assert snapshot["atr_14"] is not None
    assert snapshot["atr_percent"] is not None
    assert snapshot["high_20"] is not None
    assert snapshot["low_20"] is not None
    assert snapshot["distance_from_20_sma"] is not None
    assert snapshot["distance_from_50_sma"] is not None


def test_get_data_freshness_flags_stale_data():
    bars_df = _sample_bars(40)
    bars_df["timestamp"] = bars_df["timestamp"] - timedelta(days=15)

    freshness = get_data_freshness(bars_df)

    assert freshness["ok"] is True
    assert freshness["is_stale"] is True
    assert freshness["freshness_label"] == "stale"
    assert freshness["age_days"] > 7


def test_malformed_ohlcv_is_handled_gracefully():
    malformed_df = pd.DataFrame(
        {
            "timestamp": pd.date_range("2026-01-01", periods=3, freq="D", tz="UTC"),
            "open": [10, 11, 12],
            "high": [11, 12, 13],
            "low": [9, 10, 11],
            "close": [10.5, 11.5, 12.5],
        }
    )

    normalized = normalize_ohlcv(malformed_df)
    snapshot = calculate_technical_snapshot(normalized)
    freshness = get_data_freshness(normalized)

    assert normalized.empty
    assert snapshot["ok"] is False
    assert "No valid OHLCV data" in snapshot["error"]
    assert freshness["ok"] is False
    assert freshness["freshness_label"] == "unknown"


def test_get_historical_bars_handles_missing_polygon_api_key(monkeypatch):
    monkeypatch.setenv("MARKET_DATA_PROVIDER", "polygon")
    monkeypatch.setattr(config, "MARKET_DATA_PROVIDER", "polygon", raising=False)
    monkeypatch.setattr(config, "POLYGON_API_KEY", None)

    result = get_historical_bars("AAPL")

    assert result["ok"] is False
    assert result["ticker"] == "AAPL"
    assert result["data"] is None
    assert "POLYGON_API_KEY is not configured" in result["error"]


def test_get_market_snapshot_ibkr_fallback_includes_data_quality(monkeypatch):
    monkeypatch.setenv("MARKET_DATA_PROVIDER", "ibkr")
    monkeypatch.setattr(config, "MARKET_DATA_PROVIDER", "ibkr", raising=False)
    monkeypatch.setattr(
        "providers.ibkr_provider.get_ibkr_market_snapshot",
        lambda ticker, lookback_days=180: {
            "ok": True,
            "ticker": ticker,
            "source": "ibkr",
            "data": {
                "quote": {"last_price": 100.0, "quote_source": "historical_bar_fallback"},
                "quote_status": "unavailable",
                "quote_fallback_used": True,
                "technical_snapshot": {"ok": True, "current_price": 100.0},
                "data_freshness": {"ok": True, "age_days": 1, "is_stale": False},
                "data_quality": {
                    "quality_label": "usable_with_warnings",
                    "price_source": "historical_bar_fallback",
                    "quote_status": "unavailable",
                    "final_recommendation_allowed": True,
                    "warnings": ["IBKR live quote unavailable; using latest historical close."],
                    "errors": [],
                },
            },
            "error": None,
        },
    )

    result = get_market_snapshot("AAPL")

    assert result["ok"] is True
    assert result["data"]["data_quality"]["quality_label"] == "usable_with_warnings"
