from analytics.filter_attribution import analyze_filter_attribution, evaluate_filter_effectiveness


def test_filter_attribution_counts_blocked_downgraded_and_allowed():
    candidates = [
        {"ticker": "AAPL", "setup_type": "breakout", "passed_constraints": True, "constraint_results_json": {"data_quality": "pass"}},
        {"ticker": "MSFT", "setup_type": "breakout", "passed_constraints": False, "rejection_reason": "data_quality stale"},
        {"ticker": "NVDA", "setup_type": "breakout", "passed_constraints": True, "constraint_results_json": {"data_quality": "usable_with_warnings", "warning": "fallback"}},
    ]
    trades = [
        {"ticker": "AAPL", "setup_type": "breakout", "outcome": "win", "entry_price": 100, "stop_loss": 95, "exit_price": 110},
        {"ticker": "NVDA", "setup_type": "breakout", "outcome": "loss", "entry_price": 100, "stop_loss": 95, "exit_price": 95},
    ]

    result = analyze_filter_attribution(candidates, trades=trades, config={"min_filter_sample": 1})
    data_quality = next(item for item in result["filters"] if item["filter_name"] == "data_quality")

    assert result["ok"] is True
    assert data_quality["applied_count"] == 3
    assert data_quality["blocked_count"] == 1
    assert data_quality["downgraded_count"] == 1
    assert data_quality["allowed_count"] == 1


def test_filter_attribution_warns_on_insufficient_sample():
    result = analyze_filter_attribution(
        [{"ticker": "AAPL", "passed_constraints": True, "constraint_results_json": {"macro_risk": "pass"}}],
        config={"min_filter_sample": 5},
    )
    macro = next(item for item in result["filters"] if item["filter_name"] == "macro_risk")

    assert macro["diagnostic_status"] == "insufficient_data"
    assert macro["warnings"]


def test_evaluate_filter_effectiveness_uses_same_schema():
    result = evaluate_filter_effectiveness(
        [{"ticker": "AAPL", "passed_constraints": False, "rejection_reason": "options gating unavailable"}],
        config={"min_filter_sample": 1},
    )

    assert result["ok"] is True
    assert any(item["filter_name"] == "options_gating" for item in result["filters"])
