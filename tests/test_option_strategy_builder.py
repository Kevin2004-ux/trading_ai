from options.strategy_builder import (
    build_bear_put_debit_spread_candidate,
    build_bull_call_debit_spread_candidate,
    build_long_call_candidate,
    build_long_put_candidate,
    build_option_strategy_candidates,
)


def _contract(option_type: str, strike: float, bid: float, ask: float, **overrides):
    contract = {
        "option_contract": f"AAPL260717{option_type[0].upper()}{int(strike * 1000):08d}",
        "underlying_ticker": "AAPL",
        "option_type": option_type,
        "strike": strike,
        "expiration": "2026-07-17",
        "days_to_expiration": 32,
        "bid": bid,
        "ask": ask,
        "mid": round((bid + ask) / 2, 2),
        "volume": 500,
        "open_interest": 2000,
        "implied_volatility": 0.3,
        "iv_rank": 35,
        "delta": 0.52 if option_type == "call" else -0.48,
        "gamma": 0.04,
        "theta": -0.04,
        "vega": 0.12,
        "underlying_price": 120.0,
    }
    contract.update(overrides)
    return contract


def _chain():
    return [
        _contract("call", 120.0, 5.8, 6.0),
        _contract("call", 125.0, 3.8, 4.0),
        _contract("call", 130.0, 2.0, 2.2),
        _contract("put", 120.0, 4.8, 5.0),
        _contract("put", 115.0, 2.8, 3.0),
        _contract("put", 110.0, 1.4, 1.6),
    ]


def _view(direction: str = "bullish"):
    return {"ticker": "AAPL", "current_price": 120.0, "option_bias": direction}


def test_long_call_candidate_builds_from_valid_chain():
    result = build_long_call_candidate(_chain()[1], _view())

    assert result["strategy_type"] == "long_call"
    assert result["net_debit"] == 4.0
    assert result["max_loss"] == 4.0
    assert result["breakeven"] == 129.0


def test_long_put_candidate_builds_from_valid_chain():
    result = build_long_put_candidate(_chain()[3], _view("bearish"))

    assert result["strategy_type"] == "long_put"
    assert result["net_debit"] == 5.0
    assert result["breakeven"] == 115.0


def test_bull_call_debit_spread_calculates_economics():
    result = build_bull_call_debit_spread_candidate(_chain()[1], _chain()[2], _view())

    assert result["strategy_type"] == "bull_call_debit_spread"
    assert result["net_debit"] == 2.0
    assert result["max_loss"] == 2.0
    assert result["max_profit"] == 3.0
    assert result["breakeven"] == 127.0


def test_bear_put_debit_spread_calculates_economics():
    result = build_bear_put_debit_spread_candidate(_chain()[3], _chain()[4], _view("bearish"))

    assert result["strategy_type"] == "bear_put_debit_spread"
    assert result["net_debit"] == 2.2
    assert result["max_loss"] == 2.2
    assert result["max_profit"] == 2.8
    assert result["breakeven"] == 117.8


def test_build_option_strategy_candidates_includes_research_structures():
    result = build_option_strategy_candidates("AAPL", _view(), _chain())
    strategy_types = {item["strategy_type"] for item in result["strategies"]}

    assert result["ok"] is True
    assert "long_call" in strategy_types
    assert "bull_call_debit_spread" in strategy_types
    assert "covered_call_research" in strategy_types
    assert "cash_secured_put_research" in strategy_types
    assert result["summary"]["strategy_count"] == len(result["strategies"])

