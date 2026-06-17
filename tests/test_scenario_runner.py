from simulation.scenario_runner import run_default_stress_suite, run_scenario_suite


def test_run_default_stress_suite_returns_structured_summary():
    result = run_default_stress_suite()

    assert result["ok"] is True
    assert result["mode"] == "stress_test"
    assert result["scenario_count"] >= 18
    assert result["failed_count"] == 0
    assert result["results"]


def test_run_scenario_suite_can_run_selected_scenarios():
    result = run_scenario_suite(scenarios=["market_gap_down", "provider_outage"])

    assert result["ok"] is True
    assert result["scenario_count"] == 2
    assert result["blocked_new_trades_count"] == 1
    assert {item["scenario_name"] for item in result["results"]} == {"market_gap_down", "provider_outage"}


def test_run_scenario_suite_reports_missing_scenario():
    result = run_scenario_suite(scenarios=["missing_scenario"])

    assert result["ok"] is False
    assert result["errors"]
