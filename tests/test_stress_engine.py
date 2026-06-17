from simulation.scenario_definitions import get_stress_scenario
from simulation.stress_engine import (
    apply_stress_scenario,
    run_stress_test_on_candidate,
    run_stress_test_on_portfolio,
)


def _scenario(name: str) -> dict:
    return get_stress_scenario(name)["scenario"]


def _candidate(**overrides):
    candidate = {
        "ticker": "AAPL",
        "asset_type": "stock",
        "direction": "long",
        "entry_price": 100.0,
        "target_price": 112.0,
        "stop_loss": 94.0,
        "risk_reward": 2.0,
        "recommendation_status": "recommendable",
        "passed": True,
    }
    candidate.update(overrides)
    return candidate


def test_apply_stress_scenario_reduces_risk_without_mutating_input():
    base = _candidate()
    result = apply_stress_scenario(base, _scenario("market_gap_down"))

    assert result["ok"] is True
    assert result["risk_impact"]["risk_multiplier"] < 1.0
    assert "stress_adjustments" not in base
    assert result["post_stress"]["stress_adjustments"]["risk_multiplier"] < 1.0


def test_blocking_scenario_blocks_candidate():
    result = run_stress_test_on_candidate(_candidate(), _scenario("provider_outage"))

    assert result["decision"]["new_trades_allowed"] is False
    assert result["post_stress"]["passed"] is False
    assert result["post_stress"]["recommendation_status"] == "rejected"


def test_rejected_candidate_is_never_unblocked_by_stress():
    result = run_stress_test_on_candidate(
        _candidate(passed=False, recommendation_status="rejected"),
        _scenario("market_gap_up"),
    )

    assert result["decision"]["new_trades_allowed"] is False
    assert result["post_stress"]["passed"] is False
    assert any("never make a rejected candidate eligible" in reason for reason in result["decision"]["reasons"])


def test_option_candidate_is_never_unblocked():
    result = run_stress_test_on_candidate(
        _candidate(asset_type="option", option_contract="AAPL 2026-07-17 C 100", recommendation_status="research_only"),
        _scenario("options_iv_spike"),
    )

    assert result["post_stress"]["recommendation_status"] == "research_only"
    assert any("never unblocks option candidates" in reason for reason in result["decision"]["reasons"])


def test_run_stress_test_on_portfolio_summarizes_drawdown():
    result = run_stress_test_on_portfolio([_candidate(), _candidate(ticker="MSFT")], _scenario("market_gap_down"))

    assert result["ok"] is True
    assert result["pre_stress"]["open_trade_count"] == 2
    assert result["risk_impact"]["estimated_drawdown_r"] < 0
