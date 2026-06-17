from execution.slippage_model import (
    classify_liquidity_tier,
    estimate_market_impact,
    estimate_option_slippage,
    estimate_stock_slippage,
)


def test_mega_cap_stock_gets_low_slippage():
    trade = {"ticker": "AAPL", "entry_price": 200.0, "average_volume_20": 50_000_000, "relative_volume": 1.0}

    result = estimate_stock_slippage(trade)

    assert result["ok"] is True
    assert result["liquidity_tier"] == "mega_cap_high_liquidity"
    assert result["estimated_slippage_percent"] < 0.1


def test_low_liquidity_stock_gets_higher_slippage():
    trade = {"ticker": "SMALL", "entry_price": 10.0, "average_volume_20": 100_000, "relative_volume": 0.4}

    result = estimate_stock_slippage(trade)

    assert result["ok"] is True
    assert result["liquidity_tier"] == "low_liquidity"
    assert result["estimated_slippage_percent"] >= 0.35
    assert result["warnings"]


def test_market_impact_increases_with_position_size():
    trade = {"ticker": "AAPL", "entry_price": 100.0, "average_volume_20": 1_000_000}
    small = estimate_market_impact(trade, {"shares": 100})
    large = estimate_market_impact(trade, {"shares": 50_000})

    assert large["market_impact_percent"] > small["market_impact_percent"]


def test_option_tight_spread_gets_good_fill_quality():
    result = estimate_option_slippage(
        {"ticker": "AAPL", "option_contract": "AAPL_CALL"},
        {"option_contract": "AAPL_CALL", "bid": 4.9, "ask": 5.1},
    )

    assert result["ok"] is True
    assert result["fill_quality"] == "good"
    assert result["estimated_fill_price"] == 5.05


def test_option_wide_spread_gets_poor_fill_quality():
    result = estimate_option_slippage(
        {"ticker": "AAPL", "option_contract": "AAPL_CALL"},
        {"option_contract": "AAPL_CALL", "bid": 4.0, "ask": 5.0},
    )

    assert result["ok"] is True
    assert result["fill_quality"] == "poor"
    assert result["warnings"]


def test_option_missing_bid_ask_is_unavailable():
    result = estimate_option_slippage({"ticker": "AAPL", "option_contract": "AAPL_CALL"}, {})

    assert result["ok"] is False
    assert result["fill_quality"] == "unavailable"
    assert result["estimated_fill_price"] is None


def test_classify_liquidity_unknown_when_volume_missing():
    result = classify_liquidity_tier({"ticker": "UNKNOWN"})

    assert result["ok"] is True
    assert result["liquidity_tier"] == "unknown"

