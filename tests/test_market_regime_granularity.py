from analytics.market_regime import determine_market_regime


def _snapshot(
    ticker: str,
    *,
    current_price: float,
    sma_20: float,
    sma_50: float,
    sma_200: float,
    atr_percent: float = 2.0,
    distance_from_20_sma: float | None = None,
):
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
                "daily_return": 0.5,
                "relative_volume": 1.2,
                "distance_from_20_sma": distance_from_20_sma if distance_from_20_sma is not None else ((current_price - sma_20) / sma_20) * 100.0,
                "distance_from_50_sma": ((current_price - sma_50) / sma_50) * 100.0,
            }
        },
    }


def test_strong_bull_trend_has_full_stock_risk():
    result = determine_market_regime(
        spy_snapshot=_snapshot("SPY", current_price=600, sma_20=590, sma_50=580, sma_200=550),
        qqq_snapshot=_snapshot("QQQ", current_price=520, sma_20=510, sma_50=500, sma_200=470),
        iwm_snapshot=_snapshot("IWM", current_price=230, sma_20=225, sma_50=220, sma_200=210),
        vix_snapshot={"ok": True, "data": {"technical_snapshot": {"current_price": 15.0}}},
        universe_snapshots=[
            _snapshot("A", current_price=10, sma_20=9, sma_50=8, sma_200=7),
            _snapshot("B", current_price=10, sma_20=9, sma_50=8, sma_200=7),
            _snapshot("C", current_price=10, sma_20=9, sma_50=8, sma_200=7),
        ],
    )

    assert result["regime"] == "strong_bull_trend"
    assert result["risk_level"] == "low"
    assert result["stock_risk_multiplier"] == 1.0
    assert "momentum_breakout" in result["allowed_setups"]


def test_high_volatility_blocks_final_recommendations():
    result = determine_market_regime(
        spy_snapshot=_snapshot("SPY", current_price=600, sma_20=590, sma_50=580, sma_200=550),
        qqq_snapshot=_snapshot("QQQ", current_price=520, sma_20=510, sma_50=500, sma_200=470),
        iwm_snapshot=_snapshot("IWM", current_price=230, sma_20=225, sma_50=220, sma_200=210),
        vix_snapshot={"ok": True, "data": {"technical_snapshot": {"current_price": 34.0}}},
    )

    assert result["regime"] == "high_volatility_risk_off"
    assert result["risk_level"] == "critical"
    assert result["stock_risk_multiplier"] == 0.0
    assert "all_final_recommendations" in result["blocked_setups"]


def test_bear_trend_uses_defensive_risk_multiplier():
    result = determine_market_regime(
        spy_snapshot=_snapshot("SPY", current_price=500, sma_20=520, sma_50=530, sma_200=540),
        qqq_snapshot=_snapshot("QQQ", current_price=410, sma_20=430, sma_50=440, sma_200=450),
        iwm_snapshot=_snapshot("IWM", current_price=190, sma_20=200, sma_50=205, sma_200=210),
        vix_snapshot={"ok": True, "data": {"technical_snapshot": {"current_price": 21.0}}},
    )

    assert result["regime"] == "bear_trend"
    assert result["risk_level"] == "high"
    assert result["stock_risk_multiplier"] == 0.35
    assert result["options_aggressiveness"] == "avoid"
