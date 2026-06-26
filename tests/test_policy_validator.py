import math

from planning import POLICY_LIMITS, validate_scan_plan
from planning.policy_validator import OPPORTUNITY_COMPONENT_KEYS, SUPPORTED_PROFILES


def _adjustment_fields(result):
    return {item["field"] for item in result["adjustments"]}


def test_stock_only_conflict_disables_options_and_preference():
    result = validate_scan_plan(
        {
            "requested_instrument": "stocks",
            "include_options": True,
            "prefer_options": True,
        }
    )

    assert result["approved_plan"]["include_options"] is False
    assert result["approved_plan"]["prefer_options"] is False
    assert result["execution_config"]["include_options"] is False
    assert "include_options" in _adjustment_fields(result)
    assert "prefer_options" in _adjustment_fields(result)


def test_options_request_when_runtime_not_ready_keeps_research_but_blocks_final_eligibility():
    result = validate_scan_plan(
        {"requested_instrument": "options", "include_options": False},
        runtime_context={"safe_to_run_options": False},
    )

    assert result["approved_plan"]["include_options"] is True
    assert result["execution_config"]["include_options"] is True
    assert result["execution_config"]["options_final_eligibility"] is False
    assert any("final option recommendations remain blocked" in warning for warning in result["warnings"])


def test_invalid_universe_and_profile_do_not_reach_execution_config():
    result = validate_scan_plan(
        {
            "universes": ["not_real", "large_cap", "large_cap"],
            "profiles": ["momentum_breakout", "fake_profile"],
        }
    )

    assert result["execution_config"]["universes"] == ["large_cap"]
    assert result["execution_config"]["profiles"] == ["momentum_breakout"]
    assert "not_real" not in result["execution_config"]["universes"]
    assert "fake_profile" not in result["execution_config"]["profiles"]
    assert {"universes", "profiles"}.issubset(_adjustment_fields(result))


def test_invalid_universe_and_empty_profiles_fall_back_safely():
    result = validate_scan_plan({"universes": ["fake"], "profiles": []})

    assert result["execution_config"]["universes"] == ["large_cap"]
    assert set(result["execution_config"]["profiles"]) == set(SUPPORTED_PROFILES)


def test_limits_are_clamped_and_ordered():
    result = validate_scan_plan(
        {
            "max_tickers": 999,
            "max_candidates": -5,
            "max_final_trades": -1,
            "min_final_trades": 9,
            "option_preferences": {
                "min_dte": 120,
                "max_dte": 30,
                "max_contracts_per_ticker": 99,
            },
            "refinement": {"max_passes": 10},
        }
    )
    config = result["execution_config"]

    assert config["max_tickers"] == 500
    assert config["max_candidates"] == 1
    assert config["max_trades"] == 0
    assert config["min_trades"] == 0
    assert config["option_min_dte"] == 90
    assert config["option_max_dte"] == 90
    assert config["max_option_contracts_per_trade"] == 10
    assert config["max_refinement_passes"] == 3


def test_invalid_weights_are_removed_and_valid_weights_normalize():
    result = validate_scan_plan(
        {
            "soft_adjustments": {
                "profile_weights": {
                    "momentum_breakout": 2,
                    "fake_profile": 4,
                    "trend_pullback": 1,
                    "oversold_reversal": -1,
                },
                "opportunity_weights": {
                    "engine_core": 3,
                    "relative_strength": 1,
                    "fake_component": 10,
                    "risk_reward": math.nan,
                },
            }
        }
    )
    soft = result["approved_plan"]["soft_adjustments"]

    assert set(soft["profile_weights"]) == {"momentum_breakout", "trend_pullback"}
    assert round(sum(soft["profile_weights"].values()), 8) == 1.0
    assert set(soft["opportunity_weights"]) == {"engine_core", "relative_strength"}
    assert round(sum(soft["opportunity_weights"].values()), 8) == 1.0


def test_all_zero_weights_fall_back_to_defaults():
    result = validate_scan_plan(
        {
            "soft_adjustments": {
                "profile_weights": {"momentum_breakout": 0, "trend_pullback": 0},
                "opportunity_weights": {"engine_core": 0, "relative_strength": 0},
            }
        }
    )
    soft = result["approved_plan"]["soft_adjustments"]

    assert set(soft["profile_weights"]) == set(SUPPORTED_PROFILES)
    assert set(soft["opportunity_weights"]) == set(OPPORTUNITY_COMPONENT_KEYS)
    assert round(sum(soft["profile_weights"].values()), 8) == 1.0
    assert round(sum(soft["opportunity_weights"].values()), 8) == 1.0


def test_unsafe_override_fields_are_ignored():
    result = validate_scan_plan(
        {
            "brokerage_execution_enabled": True,
            "paper_trading_only": False,
            "disable_data_quality": True,
            "bypass_constraints": True,
            "allow_unquoted_options": True,
            "auto_log_blocked": True,
        }
    )

    assert result["execution_config"]["paper_trading_only"] is True
    assert result["execution_config"]["brokerage_execution_enabled"] is False
    assert all(field in _adjustment_fields(result) for field in {
        "brokerage_execution_enabled",
        "paper_trading_only",
        "disable_data_quality",
        "bypass_constraints",
        "allow_unquoted_options",
        "auto_log_blocked",
    })
    assert any("Strict stock constraints cannot be bypassed" in rule for rule in result["immutable_rules"])


def test_validator_is_deterministic_for_identical_input():
    proposed = {
        "requested_instrument": "both",
        "universes": ["large_cap", "active"],
        "profiles": ["momentum_breakout"],
        "include_options": True,
        "soft_adjustments": {"minimum_opportunity_score": 72},
    }

    first = validate_scan_plan(proposed, runtime_context={"safe_to_run_options": False})
    second = validate_scan_plan(proposed, runtime_context={"safe_to_run_options": False})

    assert first["approved_plan"] == second["approved_plan"]
    assert first["execution_config"] == second["execution_config"]
    assert first["adjustments"] == second["adjustments"]
    assert first["warnings"] == second["warnings"]
    assert first["errors"] == second["errors"]


def test_custom_ticker_validation_normalizes_and_falls_back_when_empty():
    valid = validate_scan_plan({"universes": ["custom"], "custom_tickers": ["aapl", "AAPL", "bad ticker", "BRK.B"]})

    assert valid["execution_config"]["universes"] == ["custom"]
    assert valid["execution_config"]["custom_tickers"] == ["AAPL", "BRK.B"]

    invalid = validate_scan_plan({"universes": ["custom"], "custom_tickers": ["bad ticker"]})

    assert invalid["execution_config"]["universes"] == ["large_cap"]
    assert invalid["execution_config"]["custom_tickers"] == []


def test_market_data_unavailable_is_warning_not_gate_relaxation():
    result = validate_scan_plan(
        {"requested_instrument": "stocks"},
        runtime_context={"market_data_available": False},
    )

    assert result["execution_config"]["market_data_ready"] is False
    assert result["execution_config"]["provider_readiness_failure"] is True
    assert any("Market-data provider readiness failed" in warning for warning in result["warnings"])
    assert result["execution_config"]["paper_trading_only"] is True
