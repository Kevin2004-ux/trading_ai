from options.strategy_builder import build_bull_call_debit_spread_candidate, build_long_call_candidate
from options.strategy_evaluator import evaluate_option_strategy


def _contract(**overrides):
    contract = {
        "option_contract": "AAPL260717C00125000",
        "underlying_ticker": "AAPL",
        "option_type": "call",
        "strike": 125.0,
        "expiration": "2026-07-17",
        "days_to_expiration": 32,
        "bid": 3.8,
        "ask": 4.0,
        "mid": 3.9,
        "volume": 500,
        "open_interest": 2000,
        "implied_volatility": 0.3,
        "iv_rank": 35,
        "delta": 0.52,
        "gamma": 0.04,
        "theta": -0.04,
        "vega": 0.12,
    }
    contract.update(overrides)
    return contract


def _view():
    return {"ticker": "AAPL", "current_price": 120.0, "option_bias": "bullish"}


def test_missing_quote_on_any_leg_blocks_strategy():
    strategy = build_long_call_candidate(_contract(bid=None, ask=None), _view())
    result = evaluate_option_strategy(strategy, _view())

    assert result["status"] == "blocked"
    assert any("bid/ask" in error for error in result["errors"])


def test_missing_iv_blocks_strategy():
    strategy = build_long_call_candidate(_contract(implied_volatility=None, iv_rank=None), _view())
    result = evaluate_option_strategy(strategy, _view())

    assert result["status"] == "blocked"
    assert any("volatility" in error.lower() for error in result["errors"])


def test_missing_greeks_blocks_strategy():
    strategy = build_long_call_candidate(_contract(delta=None), _view())
    result = evaluate_option_strategy(strategy, _view())

    assert result["status"] == "blocked"
    assert any("greeks" in error.lower() or "delta" in error.lower() for error in result["errors"])


def test_dte_under_seven_blocks_strategy():
    strategy = build_long_call_candidate(_contract(days_to_expiration=4), _view())
    result = evaluate_option_strategy(strategy, _view())

    assert result["status"] == "blocked"
    assert any("DTE under 7" in error for error in result["errors"])


def test_wide_spread_blocks_or_research_only():
    strategy = build_long_call_candidate(_contract(bid=3.0, ask=5.0, mid=4.0), _view())
    result = evaluate_option_strategy(strategy, _view())

    assert result["status"] in {"blocked", "research_only"}


def test_expensive_iv_penalizes_long_premium():
    strategy = build_long_call_candidate(_contract(implied_volatility=0.8, iv_rank=92), _view())
    result = evaluate_option_strategy(strategy, _view())

    assert result["status"] == "blocked"
    assert any("Expensive IV" in error for error in result["errors"])


def test_debit_spread_can_rank_above_long_call_when_iv_elevated():
    long_call = build_long_call_candidate(_contract(implied_volatility=0.55, iv_rank=68), _view())
    spread = build_bull_call_debit_spread_candidate(
        _contract(option_contract="LONG", strike=125.0, bid=3.8, ask=4.0, implied_volatility=0.55, iv_rank=68),
        _contract(option_contract="SHORT", strike=130.0, bid=2.0, ask=2.2, delta=0.35, implied_volatility=0.55, iv_rank=68),
        _view(),
    )

    assert spread["score"] >= long_call["score"]


def test_strategy_must_align_with_underlying_thesis():
    strategy = build_long_call_candidate(_contract(), {"ticker": "AAPL", "current_price": 120.0, "option_bias": "bearish"})

    assert strategy["status"] == "blocked"
    assert strategy["evaluation"]["expected_move_alignment"] == "conflict"

