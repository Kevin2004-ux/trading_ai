from research.short_interest import evaluate_borrow_pressure, evaluate_short_interest


def _snapshot(strong: bool = True):
    return {
        "data": {
            "technical_snapshot": {
                "current_price": 120.0 if strong else 95.0,
                "sma_20": 110.0,
                "sma_50": 100.0,
                "high_20": 121.0,
                "relative_volume": 2.0 if strong else 0.8,
            }
        }
    }


def test_short_interest_classification_low_medium_high_extreme():
    assert evaluate_short_interest("AAPL", {"short_interest_percent_float": 4})["short_interest_level"] == "low"
    assert evaluate_short_interest("AAPL", {"short_interest_percent_float": 10})["short_interest_level"] == "medium"
    assert evaluate_short_interest("AAPL", {"short_interest_percent_float": 20})["short_interest_level"] == "high"
    assert evaluate_short_interest("AAPL", {"short_interest_percent_float": 30})["short_interest_level"] == "extreme"


def test_days_to_cover_classifies_squeeze_risk():
    assert evaluate_short_interest("AAPL", {"days_to_cover": 6})["squeeze_risk"] == "high"
    assert evaluate_short_interest("AAPL", {"days_to_cover": 11})["squeeze_risk"] == "extreme"


def test_extreme_short_interest_supports_strong_long_squeeze_but_reduces_risk():
    result = evaluate_short_interest(
        "AAPL",
        {"short_interest_percent_float": 30, "days_to_cover": 7},
        market_snapshot=_snapshot(strong=True),
        config={"direction": "long", "setup_type": "momentum_breakout"},
    )

    assert result["trade_impact"] == "supportive"
    assert result["score_adjustment"] > 0
    assert result["risk_multiplier"] < 1.0


def test_extreme_short_interest_downgrades_weak_long_setup():
    result = evaluate_short_interest(
        "AAPL",
        {"short_interest_percent_float": 30, "days_to_cover": 7},
        market_snapshot=_snapshot(strong=False),
        config={"direction": "long", "setup_type": "trend_candidate"},
    )

    assert result["trade_impact"] == "caution"
    assert result["score_adjustment"] < 0


def test_extreme_short_interest_blocks_short_candidate():
    result = evaluate_short_interest(
        "AAPL",
        {"short_interest_percent_float": 30, "days_to_cover": 8},
        config={"direction": "short"},
    )

    assert result["trade_impact"] == "blocking"
    assert result["risk_multiplier"] == 0.0


def test_unknown_short_data_warns_without_crashing():
    result = evaluate_short_interest("AAPL")

    assert result["ok"] is True
    assert result["short_interest_level"] == "unknown"
    assert result["warnings"]


def test_high_borrow_pressure_blocks_short_candidates():
    result = evaluate_borrow_pressure("AAPL", {"borrow_rate": 15.0, "borrow_available": True})

    assert result["borrow_pressure"] == "high"
    assert result["short_trade_allowed"] is False


def test_unknown_borrow_warns_but_does_not_block_long_stock_trades():
    result = evaluate_borrow_pressure("AAPL")

    assert result["borrow_pressure"] == "unknown"
    assert result["short_trade_allowed"] is True
    assert result["warnings"]

