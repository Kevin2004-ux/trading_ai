from analytics.market_regime import (
    analyze_market_breadth,
    apply_regime_to_trade_selection,
    determine_market_regime,
    get_market_regime_snapshot,
)


def _snapshot(
    ticker: str,
    *,
    current_price: float,
    sma_20: float,
    sma_50: float,
    sma_200: float,
    atr_percent: float = 2.0,
    daily_return: float = 0.5,
    relative_volume: float = 1.3,
    distance_from_20_sma: float | None = None,
    distance_from_50_sma: float | None = None,
) -> dict:
    return {
        "ok": True,
        "ticker": ticker,
        "data": {
            "technical_snapshot": {
                "current_price": current_price,
                "sma_20": sma_20,
                "sma_50": sma_50,
                "sma_200": sma_200,
                "atr_percent": atr_percent,
                "daily_return": daily_return,
                "relative_volume": relative_volume,
                "distance_from_20_sma": distance_from_20_sma if distance_from_20_sma is not None else ((current_price - sma_20) / sma_20) * 100.0,
                "distance_from_50_sma": distance_from_50_sma if distance_from_50_sma is not None else ((current_price - sma_50) / sma_50) * 100.0,
            }
        },
    }


def _selection_result(count: int = 4) -> dict:
    selected = []
    for index in range(count):
        selected.append(
            {
                "ticker": f"TICK{index}",
                "recommendation_status": "recommendable",
                "score": 85.0 - index,
            }
        )
    return {
        "ok": True,
        "selected_trades": selected,
        "watchlist_alternatives": [],
        "rejected_for_portfolio_limits": [],
        "selection_summary": {
            "max_trades": 5,
            "min_trades": 2,
            "selected_count": count,
            "watchlist_count": 0,
            "message": "Initial selection complete.",
        },
        "errors": [],
    }


def test_bullish_indexes_without_breadth_produce_weak_bull_chop():
    result = determine_market_regime(
        spy_snapshot=_snapshot("SPY", current_price=600, sma_20=590, sma_50=580, sma_200=550),
        qqq_snapshot=_snapshot("QQQ", current_price=520, sma_20=510, sma_50=500, sma_200=470),
        iwm_snapshot=_snapshot("IWM", current_price=230, sma_20=225, sma_50=220, sma_200=210),
        vix_snapshot={"ok": True, "ticker": "VIX", "data": {"technical_snapshot": {"current_price": 15.0}}},
    )

    assert result["ok"] is True
    assert result["regime"] == "weak_bull_chop"
    assert result["long_bias"] is True


def test_extended_indexes_produce_risk_on_extended():
    result = determine_market_regime(
        spy_snapshot=_snapshot("SPY", current_price=620, sma_20=575, sma_50=560, sma_200=540, distance_from_20_sma=7.8),
        qqq_snapshot=_snapshot("QQQ", current_price=540, sma_20=500, sma_50=490, sma_200=460, distance_from_20_sma=8.0),
        iwm_snapshot=_snapshot("IWM", current_price=235, sma_20=225, sma_50=220, sma_200=210),
        vix_snapshot={"ok": True, "ticker": "VIX", "data": {"technical_snapshot": {"current_price": 17.0}}},
    )

    assert result["regime"] == "weak_bull_chop"


def test_bearish_indexes_produce_risk_off_downtrend():
    result = determine_market_regime(
        spy_snapshot=_snapshot("SPY", current_price=500, sma_20=520, sma_50=530, sma_200=540),
        qqq_snapshot=_snapshot("QQQ", current_price=410, sma_20=430, sma_50=440, sma_200=450),
        iwm_snapshot=_snapshot("IWM", current_price=190, sma_20=200, sma_50=205, sma_200=210),
        vix_snapshot={"ok": True, "ticker": "VIX", "data": {"technical_snapshot": {"current_price": 21.0}}},
    )

    assert result["regime"] == "bear_trend"
    assert result["trade_aggressiveness"] == "defensive"


def test_high_vix_produces_high_volatility():
    result = determine_market_regime(
        spy_snapshot=_snapshot("SPY", current_price=600, sma_20=590, sma_50=580, sma_200=550),
        qqq_snapshot=_snapshot("QQQ", current_price=520, sma_20=510, sma_50=500, sma_200=470),
        iwm_snapshot=_snapshot("IWM", current_price=230, sma_20=225, sma_50=220, sma_200=210),
        vix_snapshot={"ok": True, "ticker": "VIX", "data": {"technical_snapshot": {"current_price": 33.0}}},
    )

    assert result["regime"] == "high_volatility_risk_off"
    assert result["options_aggressiveness"] == "avoid"


def test_missing_data_returns_unknown_cleanly():
    result = determine_market_regime()

    assert result["ok"] is True
    assert result["regime"] == "unknown"


def test_market_regime_falls_back_to_spy_atr_when_vix_unavailable():
    result = determine_market_regime(
        spy_snapshot=_snapshot("SPY", current_price=600, sma_20=590, sma_50=580, sma_200=550, atr_percent=3.2),
        qqq_snapshot=_snapshot("QQQ", current_price=520, sma_20=510, sma_50=500, sma_200=470),
        iwm_snapshot=_snapshot("IWM", current_price=230, sma_20=225, sma_50=220, sma_200=210),
        vix_snapshot={
            "ok": False,
            "ticker": "VIX",
            "error": "IBKR VIX stock-contract lookup skipped. VIX is an index, not a SMART-routed stock.",
        },
    )

    volatility_context = result["index_context"]["VIX"]

    assert result["ok"] is True
    assert volatility_context["source"] == "SPY_ATR"
    assert volatility_context["spy_atr_percent"] == 3.2
    assert any("VIX unavailable" in warning for warning in result["warnings"])


def test_get_market_regime_snapshot_skips_ibkr_vix_stock_lookup(monkeypatch):
    requested = []

    def fake_snapshot(ticker, lookback_days=180):
        requested.append(ticker)
        if ticker == "VIX":
            raise AssertionError("VIX must not be requested as a normal stock.")
        return _snapshot(ticker, current_price=600, sma_20=590, sma_50=580, sma_200=550, atr_percent=2.1)

    monkeypatch.setattr("analytics.market_regime.is_ibkr_market_data_provider", lambda: True)
    monkeypatch.setattr("analytics.market_regime.get_market_snapshot", fake_snapshot)

    result = get_market_regime_snapshot(include_breadth=False)

    assert result["ok"] is True
    assert "VIX" not in requested
    assert result["snapshot_status"]["VIX"] == "fallback"
    assert result["index_context"]["VIX"]["source"] == "SPY_ATR"
    assert any("VIX unavailable" in warning for warning in result["warnings"])


def test_breadth_calculation_works():
    breadth = analyze_market_breadth(
        [
            _snapshot("A", current_price=10, sma_20=9, sma_50=8, sma_200=7, daily_return=1.0, relative_volume=1.4),
            _snapshot("B", current_price=10, sma_20=11, sma_50=12, sma_200=13, daily_return=-1.0, relative_volume=0.9),
            _snapshot("C", current_price=10, sma_20=9, sma_50=9, sma_200=8, daily_return=0.5, relative_volume=1.5),
            _snapshot("D", current_price=10, sma_20=10.5, sma_50=9.8, sma_200=8.5, daily_return=0.2, relative_volume=1.3),
        ]
    )

    assert breadth["ok"] is True
    assert breadth["sample_size"] == 4
    assert breadth["percent_above_sma_20"] == 50.0
    assert breadth["percent_above_sma_50"] == 75.0
    assert breadth["percent_positive_daily_return"] == 75.0


def test_apply_regime_to_trade_selection_reduces_selected_trades_in_risk_off():
    adjusted = apply_regime_to_trade_selection(
        _selection_result(4),
        {
            "ok": True,
            "regime": "risk_off_downtrend",
            "trade_aggressiveness": "none",
            "max_trades_adjustment": -5,
            "options_aggressiveness": "avoid",
            "risk_flags": ["Multiple major indexes are below key moving averages."],
            "summary": "Risk off.",
        },
    )

    assert adjusted["ok"] is True
    assert adjusted["selected_trades"] == []
    assert adjusted["watchlist_alternatives"]
    assert adjusted["market_regime"]["regime"] == "risk_off_downtrend"
