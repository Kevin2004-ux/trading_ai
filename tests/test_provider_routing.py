from __future__ import annotations

import config
from realtime import market_data, options_chain


def test_market_data_routing_uses_ibkr_when_selected(monkeypatch):
    monkeypatch.setenv("MARKET_DATA_PROVIDER", "ibkr")
    monkeypatch.setattr(config, "MARKET_DATA_PROVIDER", "ibkr", raising=False)
    monkeypatch.setattr(
        "providers.ibkr_provider.get_ibkr_market_snapshot",
        lambda ticker, lookback_days=180: {
            "ok": True,
            "ticker": ticker,
            "source": "ibkr",
            "data": {"row_count": 1},
            "error": None,
        },
    )

    result = market_data.get_market_snapshot("AAPL")

    assert result["ok"] is True
    assert result["source"] == "ibkr"


def test_market_data_routing_preserves_polygon_default(monkeypatch):
    monkeypatch.delenv("MARKET_DATA_PROVIDER", raising=False)
    monkeypatch.setattr(config, "MARKET_DATA_PROVIDER", "polygon", raising=False)
    monkeypatch.setattr(config, "POLYGON_API_KEY", None)

    result = market_data.get_historical_bars("AAPL")

    assert result["ok"] is False
    assert result["source"] == "polygon"
    assert "POLYGON_API_KEY" in result["error"]


def test_options_routing_uses_ibkr_when_selected(monkeypatch):
    monkeypatch.setenv("OPTIONS_DATA_PROVIDER", "ibkr")
    monkeypatch.setattr(config, "OPTIONS_DATA_PROVIDER", "ibkr", raising=False)
    monkeypatch.setattr(
        "providers.ibkr_provider.get_ibkr_options_chain",
        lambda ticker, expiration=None, min_days_to_expiration=14, max_days_to_expiration=56: {
            "ok": False,
            "ticker": ticker,
            "source": "ibkr",
            "data": {"contracts": [], "row_count": 0},
            "error": "partial",
        },
    )

    result = options_chain.get_options_chain("AAPL")

    assert result["ok"] is False
    assert result["source"] == "ibkr"


def test_options_routing_preserves_polygon_default(monkeypatch):
    monkeypatch.delenv("OPTIONS_DATA_PROVIDER", raising=False)
    monkeypatch.setattr(config, "OPTIONS_DATA_PROVIDER", "polygon", raising=False)
    monkeypatch.setattr(config, "POLYGON_API_KEY", None)

    result = options_chain.get_options_chain("AAPL")

    assert result["ok"] is False
    assert result["source"] == "unavailable"
    assert "POLYGON_API_KEY" in result["error"]
