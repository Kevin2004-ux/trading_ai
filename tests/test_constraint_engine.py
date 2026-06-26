from engine.constraint_engine import (
    evaluate_option_constraints,
    evaluate_stock_constraints,
)


def _strong_stock_candidate() -> dict:
    return {
        "ticker": "AAPL",
        "asset_type": "equity",
        "direction": "long",
        "setup_type": "breakout",
        "current_price": 120.0,
        "sma_20": 110.0,
        "sma_50": 105.0,
        "sma_200": 100.0,
        "average_volume_20": 2_500_000,
        "relative_volume": 1.8,
        "atr_percent": 0.04,
        "risk_reward": 3.2,
        "days_until_earnings": 20,
        "data_freshness": {"ok": True, "freshness_label": "fresh"},
    }


def _strong_option_candidate() -> dict:
    return {
        "ticker": "AAPL240719C00120000",
        "underlying_ticker": "AAPL",
        "option_contract": "AAPL240719C00120000",
        "direction": "long_call",
        "strategy": "long_call",
        "bid": 4.8,
        "ask": 5.0,
        "mid": 4.9,
        "volume": 350,
        "open_interest": 1500,
        "iv_rank": 45,
        "days_to_expiration": 28,
        "risk_reward": 2.8,
    }


def test_strong_stock_candidate_passes_and_is_recommendable():
    result = evaluate_stock_constraints(_strong_stock_candidate())

    assert result["passed"] is True
    assert result["recommendation_status"] == "recommendable"
    assert result["score"] >= 80
    assert result["failed_constraints"] == []


def test_stock_candidate_fails_because_relative_volume_is_too_low():
    candidate = _strong_stock_candidate()
    candidate["relative_volume"] = 0.9

    result = evaluate_stock_constraints(candidate)

    assert result["passed"] is False
    assert result["recommendation_status"] == "rejected"
    assert "minimum_relative_volume" in result["failed_constraints"]


def test_stock_candidate_fails_because_price_is_below_moving_averages():
    candidate = _strong_stock_candidate()
    candidate["current_price"] = 95.0

    result = evaluate_stock_constraints(candidate)

    assert result["passed"] is False
    assert result["recommendation_status"] == "rejected"
    assert "price_above_sma_20" in result["failed_constraints"]
    assert "price_above_sma_50" in result["failed_constraints"]
    assert result["constraint_results"]["price_above_sma_20"]["message"] == "Price is below SMA 20 or SMA 20 is missing."
    assert result["constraint_results"]["price_above_sma_50"]["message"] == "Price is below SMA 50 or SMA 50 is missing."


def test_disabled_sma_requirements_pass_with_accurate_below_sma_messages():
    candidate = _strong_stock_candidate()
    candidate["current_price"] = 100.0
    candidate["sma_20"] = 110.0
    candidate["sma_50"] = 105.0

    result = evaluate_stock_constraints(
        candidate,
        config={
            "require_price_above_sma_20": False,
            "require_price_above_sma_50": False,
        },
    )

    sma_20 = result["constraint_results"]["price_above_sma_20"]
    sma_50 = result["constraint_results"]["price_above_sma_50"]
    assert result["passed"] is True
    assert "price_above_sma_20" not in result["failed_constraints"]
    assert "price_above_sma_50" not in result["failed_constraints"]
    assert sma_20["passed"] is True
    assert sma_20["required"] == "not required by profile"
    assert sma_20["message"] == "Price is below SMA 20, but this profile does not require price above SMA 20."
    assert sma_50["passed"] is True
    assert sma_50["required"] == "not required by profile"
    assert sma_50["message"] == "Price is below SMA 50, but this profile does not require price above SMA 50."
    expected_status = "recommendable" if result["score"] >= result["config"]["minimum_score_to_recommend"] else "watchlist"
    assert result["recommendation_status"] == expected_status


def test_enabled_sma_requirement_with_price_above_sma_passes_with_normal_message():
    candidate = _strong_stock_candidate()

    result = evaluate_stock_constraints(candidate)

    assert result["constraint_results"]["price_above_sma_20"]["passed"] is True
    assert result["constraint_results"]["price_above_sma_20"]["message"] == "Price is above SMA 20."
    assert result["constraint_results"]["price_above_sma_50"]["passed"] is True
    assert result["constraint_results"]["price_above_sma_50"]["message"] == "Price is above SMA 50."


def test_sma_message_fix_does_not_change_score_calculation():
    candidate = _strong_stock_candidate()
    candidate["current_price"] = 100.0
    candidate["sma_20"] = 110.0
    candidate["sma_50"] = 105.0

    enabled = evaluate_stock_constraints(candidate)
    disabled = evaluate_stock_constraints(
        candidate,
        config={
            "require_price_above_sma_20": False,
            "require_price_above_sma_50": False,
        },
    )

    assert disabled["score"] == enabled["score"]
    assert enabled["recommendation_status"] == "rejected"
    expected_disabled_status = "recommendable" if disabled["score"] >= disabled["config"]["minimum_score_to_recommend"] else "watchlist"
    assert disabled["recommendation_status"] == expected_disabled_status


def test_stock_candidate_with_lower_score_becomes_watchlist():
    candidate = _strong_stock_candidate()
    candidate["relative_volume"] = 1.21
    candidate["average_volume_20"] = 1_000_100
    candidate["risk_reward"] = 2.02
    candidate["atr_percent"] = 0.11
    candidate["days_until_earnings"] = 8
    candidate["data_freshness"] = {"ok": True, "freshness_label": "slightly_stale"}

    result = evaluate_stock_constraints(candidate)

    assert result["passed"] is True
    assert result["recommendation_status"] == "watchlist"
    assert result["score"] < 80


def test_strong_option_candidate_passes_when_underlying_stock_passed():
    underlying_result = evaluate_stock_constraints(_strong_stock_candidate())

    result = evaluate_option_constraints(_strong_option_candidate(), underlying_result=underlying_result)

    assert result["passed"] is True
    assert result["recommendation_status"] == "recommendable"
    assert result["score"] >= 80


def test_option_candidate_fails_due_to_wide_bid_ask_spread():
    underlying_result = evaluate_stock_constraints(_strong_stock_candidate())
    option_candidate = _strong_option_candidate()
    option_candidate["bid"] = 4.0
    option_candidate["ask"] = 5.0
    option_candidate["mid"] = 4.5

    result = evaluate_option_constraints(option_candidate, underlying_result=underlying_result)

    assert result["passed"] is False
    assert result["recommendation_status"] == "rejected"
    assert "maximum_bid_ask_spread_percent" in result["failed_constraints"]


def test_option_candidate_fails_when_underlying_failed_and_required():
    failed_underlying = evaluate_stock_constraints({"ticker": "AAPL"})

    result = evaluate_option_constraints(_strong_option_candidate(), underlying_result=failed_underlying)

    assert result["passed"] is False
    assert result["recommendation_status"] == "rejected"
    assert "underlying_passed_constraints" in result["failed_constraints"]


def test_missing_fields_produce_clean_rejected_outputs_not_crashes():
    stock_result = evaluate_stock_constraints({"ticker": "AAPL"})
    option_result = evaluate_option_constraints({"ticker": "OPT"}, underlying_result=None)

    assert stock_result["passed"] is False
    assert stock_result["recommendation_status"] == "rejected"
    assert isinstance(stock_result["failed_constraints"], list)
    assert isinstance(stock_result["rejection_reason"], str)

    assert option_result["passed"] is False
    assert option_result["recommendation_status"] == "rejected"
    assert isinstance(option_result["failed_constraints"], list)
    assert isinstance(option_result["rejection_reason"], str)
