from simulation.data_failure_simulator import (
    simulate_partial_scan_timeout,
    simulate_provider_outage,
    simulate_stale_data,
)


def test_simulate_provider_outage_blocks_final_recommendations():
    result = simulate_provider_outage(["aapl"], provider="ibkr")

    assert result["ok"] is True
    assert result["data_quality"]["quality_label"] == "unavailable"
    assert result["data_quality"]["final_recommendation_allowed"] is False
    assert result["tickers"] == ["AAPL"]


def test_simulate_stale_data_marks_snapshot_stale():
    result = simulate_stale_data({"ok": True, "data": {}}, stale_days=7)

    assert result["ok"] is True
    assert result["market_snapshot"]["ok"] is False
    assert result["market_snapshot"]["data"]["freshness"]["is_stale"] is True
    assert result["data_quality"]["final_recommendation_allowed"] is False


def test_simulate_partial_scan_timeout_preserves_partial_output():
    result = simulate_partial_scan_timeout({"ok": True, "best_candidates": [{"ticker": "AAPL"}, {"ticker": "MSFT"}]})

    assert result["ok"] is True
    assert result["scan_result"]["ok"] is True
    assert result["scan_result"]["scan_execution_summary"]["partial_results_used"] is True
    assert result["data_quality"]["final_recommendation_allowed"] is True
