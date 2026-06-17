from analytics.trade_error_analysis import analyze_trade_errors, classify_trade_failure


def test_classify_trade_failure_detects_stop_too_tight():
    result = classify_trade_failure(
        {
            "id": 1,
            "ticker": "AAPL",
            "outcome": "loss",
            "entry_price": 100.0,
            "stop_loss": 95.0,
            "exit_price": 95.0,
            "max_drawdown": -1.2,
            "max_gain": 0.1,
        }
    )

    assert result["ok"] is True
    assert "stop_too_tight" in result["failure_categories"]


def test_classify_trade_failure_detects_macro_news_and_filing_risk():
    result = classify_trade_failure(
        {
            "ticker": "MSFT",
            "outcome": "loss",
            "risk_reward": 1.5,
            "data_snapshot_json": {
                "macro_risk": "FOMC",
                "news_sentiment": "negative headline downgrade",
                "filing_sentiment": "8-K filing risk",
            },
        }
    )

    assert "poor_risk_reward" in result["failure_categories"]
    assert "macro_event_risk" in result["failure_categories"]
    assert "news_risk" in result["failure_categories"]
    assert "earnings_or_filing_risk" in result["failure_categories"]


def test_analyze_trade_errors_returns_top_failure_modes():
    trades = [
        {"ticker": "AAPL", "outcome": "loss", "entry_price": 100, "stop_loss": 95, "exit_price": 95, "max_drawdown": -1.2, "max_gain": 0.1},
        {"ticker": "MSFT", "outcome": "win", "entry_price": 100, "stop_loss": 95, "exit_price": 110},
    ]

    result = analyze_trade_errors(trades)

    assert result["ok"] is True
    assert result["top_failure_modes"][0]["category"] == "stop_too_tight"
    assert result["trade_diagnostics"][0]["ticker"] == "AAPL"


def test_analyze_trade_errors_warns_without_losers():
    result = analyze_trade_errors([{"ticker": "AAPL", "outcome": "win", "risk_reward": 2.0}])

    assert result["ok"] is True
    assert result["warnings"]
