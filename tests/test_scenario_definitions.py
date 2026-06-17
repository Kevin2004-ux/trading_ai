from simulation.scenario_definitions import get_stress_scenario, list_stress_scenarios


def test_list_stress_scenarios_includes_required_schema():
    result = list_stress_scenarios()

    assert result["ok"] is True
    assert result["scenario_count"] >= 18
    scenario = result["scenarios"][0]
    assert {
        "scenario_name",
        "description",
        "severity",
        "affected_components",
        "market_shocks",
        "data_shocks",
        "risk_shocks",
        "expected_behavior",
    } <= set(scenario)


def test_get_stress_scenario_returns_named_scenario():
    result = get_stress_scenario("market_gap_down")

    assert result["ok"] is True
    assert result["scenario"]["scenario_name"] == "market_gap_down"


def test_get_stress_scenario_missing_returns_clean_error():
    result = get_stress_scenario("not_real")

    assert result["ok"] is False
    assert result["scenario"] is None
    assert result["errors"]
