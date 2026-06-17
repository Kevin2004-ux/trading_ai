from analytics.strategy_diagnostics import analyze_setup_performance, diagnose_strategy_health


def _trade(setup: str, outcome: str, exit_price: float) -> dict:
    return {
        "ticker": setup.upper()[:4],
        "setup_type": setup,
        "outcome": outcome,
        "entry_price": 100.0,
        "stop_loss": 95.0,
        "exit_price": exit_price,
        "holding_period_days": 5,
    }


def test_setup_diagnostics_groups_by_setup_type():
    trades = [_trade("momentum_breakout", "win", 110.0), _trade("mean_reversion", "loss", 95.0)]

    result = analyze_setup_performance(trades, config={"minimum_sample_size": 1})

    assert result["ok"] is True
    assert {setup["setup_type"] for setup in result["setups"]} == {"momentum_breakout", "mean_reversion"}


def test_strong_setup_classified_strong_or_healthy():
    trades = [_trade("momentum_breakout", "win", 110.0) for _ in range(8)]

    result = analyze_setup_performance(trades)
    setup = result["setups"][0]

    assert setup["setup_type"] == "momentum_breakout"
    assert setup["status"] in {"strong", "healthy"}
    assert setup["expectancy_r"] > 0


def test_weak_setup_classified_disabled_candidate():
    trades = [_trade("failed_breakout", "loss", 91.0) for _ in range(15)]

    result = analyze_setup_performance(trades)
    setup = result["setups"][0]

    assert setup["status"] == "disabled_candidate"
    assert any("Disabled-candidate" in warning for warning in setup["warnings"])


def test_diagnose_strategy_health_includes_setup_decay_context():
    trades = [_trade("failed_breakout", "loss", 95.0) for _ in range(10)]

    result = diagnose_strategy_health(trades)

    assert result["ok"] is True
    assert "setup_decay_context" in result
    assert result["overall_status"] in {"degrading", "critical_review", "stable_or_insufficient_sample"}
