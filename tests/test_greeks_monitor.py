from options.greeks_monitor import evaluate_option_greeks, evaluate_portfolio_greeks


def _quote(**overrides):
    quote = {
        "option_contract": "AAPL260717C00125000",
        "mid": 4.0,
        "days_to_expiration": 30,
        "delta": 0.5,
        "gamma": 0.04,
        "theta": -0.04,
        "vega": 0.12,
        "rho": 0.02,
    }
    quote.update(overrides)
    return quote


def test_complete_greeks_return_good_or_usable():
    result = evaluate_option_greeks(_quote())

    assert result["ok"] is True
    assert result["greeks_quality"] == "good"
    assert result["risk_level"] == "low"


def test_missing_delta_blocks_final_eligibility():
    result = evaluate_option_greeks(_quote(delta=None))

    assert result["ok"] is False
    assert result["greeks_quality"] == "unavailable"
    assert result["risk_level"] == "blocked"


def test_high_gamma_near_expiration_warns_high_risk():
    result = evaluate_option_greeks(_quote(days_to_expiration=4, gamma=0.22))

    assert result["ok"] is True
    assert result["risk_level"] == "high"
    assert any("High gamma" in warning for warning in result["warnings"])


def test_low_delta_warns_speculative_contract():
    result = evaluate_option_greeks(_quote(delta=0.1))

    assert result["ok"] is True
    assert result["risk_level"] == "medium"
    assert any("low-probability" in warning for warning in result["warnings"])


def test_portfolio_greeks_aggregates_open_option_exposure():
    result = evaluate_portfolio_greeks([_quote(contracts=2), _quote(option_contract="MSFT260717C00300000", delta=-0.2)])

    assert result["ok"] is True
    assert result["contract"] == "portfolio"
    assert result["delta"] == 0.8

