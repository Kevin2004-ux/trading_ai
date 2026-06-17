from alerts.alert_rules import evaluate_alert_rules


def _types(result: dict) -> set[str]:
    return {alert["alert_type"] for alert in result["alerts"]}


def test_failed_paper_cycle_creates_critical_alert():
    result = evaluate_alert_rules(
        job_result={"ok": False, "job_name": "weekly_paper_cycle", "job_type": "paper_cycle", "status": "failed"}
    )

    assert result["ok"] is True
    assert "job_failed" in _types(result)
    assert result["alerts"][0]["severity"] == "critical"


def test_no_trade_selected_creates_info_alert():
    result = evaluate_alert_rules(trading_result={"ok": True, "summary": {"selected_count": 0}})

    assert "no_trade_selected" in _types(result)


def test_data_quality_and_risk_blocks_create_alerts():
    result = evaluate_alert_rules(
        trading_result={
            "ok": True,
            "summary": {
                "selected_count": 1,
                "data_quality": {"worst_quality_label": "poor"},
                "circuit_breaker": {"new_trades_allowed": False},
                "macro_risk": {"new_trades_allowed": False},
                "concentration_summary": {"blocked_count": 1},
                "option_risk_summary": {"blocked_count": 2},
                "memory_summary": {"ignored_count": 1},
                "research_risk_summary": {"blocking_count": 1},
            },
        }
    )

    alert_types = _types(result)
    assert "data_quality_degraded" in alert_types
    assert "circuit_breaker_blocked" in alert_types
    assert "macro_critical_block" in alert_types
    assert "concentration_block" in alert_types
    assert "options_data_unavailable" in alert_types
    assert "memory_quality_failed" in alert_types
    assert "critical_news_or_filing_risk" in alert_types


def test_health_failures_create_startup_audit_schema_and_provider_alerts():
    result = evaluate_alert_rules(
        health_result={
            "ok": False,
            "audit_chain": {"ok": False},
            "schema_validation": {"ok": False},
            "checks": {"market_data": {"status": "unavailable", "error": "Missing key"}},
        }
    )

    alert_types = _types(result)
    assert "startup_not_ready" in alert_types
    assert "audit_chain_failed" in alert_types
    assert "schema_validation_failed" in alert_types
    assert "provider_unavailable" in alert_types


def test_performance_alerts_warn_on_negative_expectancy_and_disabled_setup():
    result = evaluate_alert_rules(
        job_result={
            "ok": True,
            "job_name": "performance_report",
            "job_type": "performance_report",
            "status": "warning",
            "result": {
                "performance_attribution": {"closed_trade_count": 12, "expectancy_r": -0.2},
                "setup_diagnostics": {"setups": [{"setup_type": "breakout", "status": "disabled_candidate"}]},
            },
        }
    )

    alert_types = _types(result)
    assert "negative_expectancy" in alert_types
    assert "setup_disabled_candidate" in alert_types


def test_performance_alerts_warn_on_repeated_data_quality_and_slippage():
    result = evaluate_alert_rules(
        job_result={
            "ok": True,
            "job_name": "performance_report",
            "job_type": "performance_report",
            "status": "warning",
            "result": {
                "filter_attribution": {
                    "filters": [
                        {"filter_name": "data_quality", "applied_count": 5, "blocked_count": 2, "downgraded_count": 1},
                        {"filter_name": "slippage_fill_quality", "applied_count": 5, "blocked_count": 3, "downgraded_count": 0},
                    ]
                }
            },
        }
    )

    alert_types = _types(result)
    assert "repeated_data_quality_failures" in alert_types
    assert "repeated_slippage_fill_issues" in alert_types


def test_stress_alerts_warn_on_failed_expected_behavior():
    result = evaluate_alert_rules(
        job_result={
            "ok": False,
            "job_name": "stress_test",
            "job_type": "stress_test",
            "status": "failed",
            "result": {
                "mode": "stress_test",
                "failed_count": 1,
                "results": [{"scenario_name": "market_gap_down", "passed_expected_behavior": False}],
            },
        }
    )

    assert "stress_test_failed_expected_behavior" in _types(result)


def test_stress_alerts_warn_on_high_portfolio_stress_loss():
    result = evaluate_alert_rules(
        job_result={
            "ok": True,
            "job_name": "stress_test",
            "job_type": "stress_test",
            "status": "warning",
            "result": {"mode": "stress_test", "estimated_total_loss_r": -4.5, "failed_count": 0},
        },
        config={"STRESS_MAX_ACCEPTABLE_LOSS_R": 3.0},
    )

    assert "portfolio_stress_loss_high" in _types(result)


def test_stress_alerts_catch_unsafe_provider_outage_behavior():
    result = evaluate_alert_rules(
        job_result={
            "ok": True,
            "job_name": "stress_test",
            "job_type": "stress_test",
            "status": "warning",
            "result": {
                "mode": "stress_test",
                "failed_count": 0,
                "results": [
                    {
                        "scenario_name": "provider_outage",
                        "passed_expected_behavior": True,
                        "stress_result": {"decision": {"new_trades_allowed": True}},
                    }
                ],
            },
        }
    )

    assert "provider_outage_not_handled_safely" in _types(result)
