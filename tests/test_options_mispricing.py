from analytics.options_mispricing import (
    black_scholes_value,
    estimate_historical_volatility,
    evaluate_option_mispricing,
    rank_options_by_value,
)


def _bars() -> list[dict]:
    prices = [
        100.0, 101.0, 102.5, 101.8, 103.0, 104.2, 103.6, 105.0, 106.1, 105.4,
        106.8, 108.1, 107.5, 109.0, 110.2, 109.6, 111.3, 112.0, 111.4, 113.2,
        114.1, 113.8, 115.0, 116.2, 115.7,
    ]
    return [{"close": price} for price in prices]


def _underlying_candidate() -> dict:
    return {
        "ticker": "AAPL",
        "current_price": 120.0,
        "entry_price": 120.0,
        "target_price": 145.0,
        "bars": _bars(),
    }


def _option_candidate(**overrides) -> dict:
    candidate = {
        "option_contract": "O:AAPL260703C00125000",
        "ticker": "O:AAPL260703C00125000",
        "underlying_ticker": "AAPL",
        "option_type": "call",
        "strike": 125.0,
        "days_to_expiration": 26,
        "mid": 3.9,
        "bid": 3.8,
        "ask": 4.0,
        "volume": 450,
        "open_interest": 1600,
        "implied_volatility": 0.32,
        "iv_rank": 18,
        "delta": 0.51,
        "spread_percent": 0.05,
        "breakeven_price": 128.9,
        "breakeven_move_percent": (128.9 - 120.0) / 120.0,
        "risk_reward": 2.6,
        "recommendation_status": "recommendable",
    }
    candidate.update(overrides)
    return candidate


def test_historical_volatility_calculation_works():
    result = estimate_historical_volatility(bars=_bars(), window=20)

    assert result["ok"] is True
    assert result["historical_volatility"] is not None
    assert result["historical_volatility"] > 0
    assert result["sample_size"] == 20


def test_historical_volatility_handles_too_little_data():
    result = estimate_historical_volatility(close_prices=[100.0, 101.0], window=20)

    assert result["ok"] is False
    assert "Not enough" in result["error"]


def test_black_scholes_call_value_works():
    result = black_scholes_value(
        option_type="call",
        underlying_price=120.0,
        strike=125.0,
        days_to_expiration=30,
        volatility=0.3,
    )

    assert result["ok"] is True
    assert result["theoretical_value"] > 0


def test_black_scholes_put_value_works():
    result = black_scholes_value(
        option_type="put",
        underlying_price=120.0,
        strike=125.0,
        days_to_expiration=30,
        volatility=0.3,
    )

    assert result["ok"] is True
    assert result["theoretical_value"] > 0


def test_invalid_black_scholes_inputs_return_clean_error():
    result = black_scholes_value(
        option_type="call",
        underlying_price=0.0,
        strike=125.0,
        days_to_expiration=30,
        volatility=0.3,
    )

    assert result["ok"] is False
    assert "underlying_price" in result["error"]


def test_option_with_reasonable_mid_iv_and_breakeven_returns_fair_or_attractive():
    result = evaluate_option_mispricing(_option_candidate(), _underlying_candidate(), historical_volatility=0.28)

    assert result["ok"] is True
    assert result["mispricing_label"] in {"fair_value", "attractive_value"}
    assert result["mispricing_score"] >= 50


def test_option_with_huge_iv_and_weak_breakeven_returns_risky_or_overpriced():
    result = evaluate_option_mispricing(
        _option_candidate(
            mid=8.5,
            implied_volatility=0.9,
            spread_percent=0.22,
            breakeven_price=150.0,
            breakeven_move_percent=0.25,
            delta=0.22,
            volume=20,
            open_interest=70,
        ),
        _underlying_candidate(),
        historical_volatility=0.22,
    )

    assert result["ok"] is True
    assert result["mispricing_label"] in {"high_iv_risky", "overpriced"}


def test_cheap_far_otm_low_delta_option_returns_low_probability_label():
    result = evaluate_option_mispricing(
        _option_candidate(
            option_contract="O:AAPL260703C00140000",
            strike=140.0,
            mid=0.55,
            bid=0.5,
            ask=0.6,
            delta=0.1,
            volume=35,
            open_interest=250,
            implied_volatility=0.38,
            breakeven_price=140.55,
            breakeven_move_percent=(140.55 - 120.0) / 120.0,
        ),
        _underlying_candidate(),
        historical_volatility=0.24,
    )

    assert result["ok"] is True
    assert result["mispricing_label"] == "cheap_but_low_probability"


def test_rank_options_by_value_orders_better_contracts_first():
    result = rank_options_by_value(
        [
            _option_candidate(option_contract="GOOD", mid=3.7, implied_volatility=0.29),
            _option_candidate(option_contract="BAD", mid=8.4, implied_volatility=0.82, spread_percent=0.2, volume=10, open_interest=50),
        ],
        _underlying_candidate(),
        historical_volatility=0.25,
    )

    assert result["ok"] is True
    assert result["ranked_candidates"][0]["option_contract"] == "GOOD"

