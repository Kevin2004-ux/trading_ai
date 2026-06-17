from analytics.performance_attribution import analyze_paper_trade_performance, calculate_r_multiple


def test_performance_attribution_calculates_core_metrics():
    trades = [
        {"ticker": "AAPL", "outcome": "win", "entry_price": 100, "stop_loss": 95, "exit_price": 110, "created_at": "2026-01-01T00:00:00+00:00", "closed_at": "2026-01-04T00:00:00+00:00"},
        {"ticker": "MSFT", "outcome": "loss", "entry_price": 50, "stop_loss": 45, "exit_price": 45, "created_at": "2026-01-02T00:00:00+00:00", "closed_at": "2026-01-04T00:00:00+00:00"},
        {"ticker": "NVDA", "outcome": "win", "entry_price": 20, "stop_loss": 18, "exit_price": 24, "created_at": "2026-01-03T00:00:00+00:00", "closed_at": "2026-01-05T00:00:00+00:00"},
        {"ticker": "SPY", "status": "open", "entry_price": 500, "stop_loss": 490},
    ]

    result = analyze_paper_trade_performance(trades, config={"min_closed_trades": 1})

    assert result["ok"] is True
    assert result["trade_count"] == 4
    assert result["closed_trade_count"] == 3
    assert result["open_trade_count"] == 1
    assert result["win_rate"] == 66.67
    assert result["avg_win_r"] == 2.0
    assert result["avg_loss_r"] == -1.0
    assert result["expectancy_r"] == 1.0
    assert result["profit_factor"] == 4.0
    assert result["max_drawdown_r"] == -1.0
    assert result["median_hold_days"] == 2.0
    assert result["best_trade"]["ticker"] == "AAPL"
    assert result["worst_trade"]["ticker"] == "MSFT"


def test_insufficient_closed_trades_returns_warning_not_failure():
    result = analyze_paper_trade_performance([{"ticker": "AAPL", "outcome": "win", "risk_reward": 2.0}])

    assert result["ok"] is True
    assert result["closed_trade_count"] == 1
    assert any("Insufficient" in warning for warning in result["warnings"])


def test_calculate_r_multiple_handles_short_trades():
    value = calculate_r_multiple({"direction": "short", "entry_price": 100, "stop_loss": 105, "exit_price": 90})

    assert value == 2.0
