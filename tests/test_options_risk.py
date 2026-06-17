from options.options_risk import evaluate_option_trade_risk


def _candidate(**overrides):
    candidate = {
        "option_contract": "AAPL260717C00125000",
        "underlying_ticker": "AAPL",
        "asset_type": "option",
        "direction": "long",
        "strategy": "long_call",
        "option_type": "call",
        "strike": 125.0,
        "expiration": "2026-07-17",
        "days_to_expiration": 32,
        "bid": 3.9,
        "ask": 4.1,
        "mid": 4.0,
        "implied_volatility": 0.28,
        "iv_rank": 18,
        "iv_percentile": 22,
        "delta": 0.52,
        "gamma": 0.04,
        "theta": -0.04,
        "vega": 0.12,
    }
    candidate.update(overrides)
    return candidate


def test_option_risk_approved_only_with_quote_iv_greeks_and_fill_quality():
    result = evaluate_option_trade_risk(_candidate())

    assert result["approved"] is True
    assert result["status"] == "approved"
    assert result["fill_quality"] in {"good", "usable"}
    assert result["iv_context"]["iv_context"] == "cheap"


def test_missing_bid_ask_blocks_option_risk():
    result = evaluate_option_trade_risk(_candidate(bid=None, ask=None))

    assert result["approved"] is False
    assert result["status"] == "blocked"
    assert any("bid/ask" in error for error in result["errors"])


def test_missing_iv_blocks_option_risk():
    result = evaluate_option_trade_risk(_candidate(implied_volatility=None, iv_rank=None))

    assert result["approved"] is False
    assert result["status"] == "blocked"
    assert any("volatility" in error.lower() for error in result["errors"])


def test_missing_greeks_blocks_option_risk():
    result = evaluate_option_trade_risk(_candidate(delta=None))

    assert result["approved"] is False
    assert result["status"] == "blocked"
    assert any("greeks" in error.lower() or "delta" in error.lower() for error in result["errors"])


def test_dte_under_seven_blocks_by_default():
    result = evaluate_option_trade_risk(_candidate(days_to_expiration=5))

    assert result["approved"] is False
    assert result["status"] == "blocked"
    assert any("DTE under 7" in error for error in result["errors"])


def test_wide_spread_blocks_or_research_only():
    result = evaluate_option_trade_risk(_candidate(bid=3.0, ask=5.0, mid=4.0))

    assert result["approved"] is False
    assert result["status"] in {"blocked", "research_only"}


def test_expensive_iv_blocks_long_premium():
    result = evaluate_option_trade_risk(_candidate(implied_volatility=0.8, iv_rank=92))

    assert result["approved"] is False
    assert result["status"] == "blocked"
    assert any("Expensive IV" in error for error in result["errors"])

