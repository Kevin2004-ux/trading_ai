import sqlite3

from paper.paper_trader import (
    get_paper_trading_summary,
    review_paper_portfolio,
    run_paper_trade_cycle,
)
from tracking.trade_logger import init_trade_tracking_db, log_recommendation, log_trade_outcome


def _seed_paper_recommendation(
    db_path: str,
    *,
    ticker: str = "AAPL",
    strategy: str = "paper_strategy",
    setup_type: str = "momentum_breakout",
):
    return log_recommendation(
        ticker=ticker,
        asset_type="stock",
        direction="long",
        strategy=strategy,
        setup_type=setup_type,
        entry_price=100.0,
        target_price=110.0,
        stop_loss=95.0,
        risk_reward=2.0,
        score=90.0,
        data_snapshot_json={"paper_trading": True, "execution_mode": "paper_trading"},
        model_outputs_json={"paper_trading": True, "execution_mode": "paper_trading"},
        db_path=db_path,
    )


def test_run_paper_trade_cycle_logs_only_valid_recommendations_and_labels_mode(monkeypatch):
    monkeypatch.setattr(
        "paper.paper_trader.run_weekly_trade_hunt",
        lambda **kwargs: {
            "ok": True,
            "mode": "weekly_trade_hunt",
            "decision_result": {
                "final_recommendations": [{"ticker": "AAPL"}],
                "logged_recommendations": [
                    {
                        "ok": True,
                        "data": {
                            "recommendation": {
                                "id": 1,
                                "ticker": "AAPL",
                                "model_outputs_json": {"paper_trading": True},
                            }
                        },
                    }
                ],
            },
            "errors": [],
        },
    )

    result = run_paper_trade_cycle()

    assert result["ok"] is True
    assert result["mode"] == "paper_trading"
    assert result["paper_trades_logged"][0]["ticker"] == "AAPL"
    assert "simulated" in result["warning"].lower()


def test_review_paper_portfolio_updates_outcomes_and_returns_simulated_performance(monkeypatch, tmp_path):
    db_path = str(tmp_path / "paper_review.db")
    init_trade_tracking_db(db_path)
    recommendation = _seed_paper_recommendation(db_path)
    log_trade_outcome(
        recommendation_id=recommendation["id"],
        outcome="win",
        exit_price=108.0,
        realized_return=8.0,
        grading_data_json={"paper_trading": True},
        db_path=db_path,
    )

    monkeypatch.setattr(
        "paper.paper_trader.monitor_open_trades",
        lambda update_outcomes=True, db_path="strategy_library.db": {
            "ok": True,
            "update_result": {
                "ok": True,
                "results": [{"recommendation_id": recommendation["id"], "outcome": "win"}],
            },
            "errors": [],
        },
    )

    result = review_paper_portfolio(db_path=db_path)

    assert result["ok"] is True
    assert result["mode"] == "paper_trading"
    assert result["win_loss_record"]["wins"] == 1
    assert result["trade_review_summary"] is not None
    assert "simulated" in result["warning"].lower()


def test_review_paper_portfolio_can_run_trade_reviews_with_memory_flag(monkeypatch, tmp_path):
    db_path = str(tmp_path / "paper_review_flags.db")
    captured = {}

    monkeypatch.setattr(
        "paper.paper_trader.monitor_open_trades",
        lambda update_outcomes=True, db_path="strategy_library.db": {
            "ok": True,
            "update_result": {"ok": True, "results": []},
            "errors": [],
        },
    )
    monkeypatch.setattr(
        "paper.paper_trader.review_closed_trades",
        lambda **kwargs: captured.update(kwargs) or {
            "ok": True,
            "reviewed_count": 0,
            "skipped_count": 0,
            "reviews": [],
            "errors": [],
        },
    )

    result = review_paper_portfolio(
        include_trade_reviews=True,
        store_review_memory=True,
        db_path=db_path,
    )

    assert result["ok"] is True
    assert captured["store_memory"] is True
    assert captured["db_path"] == db_path
    assert result["trade_review_summary"]["reviewed_count"] == 0


def test_get_paper_trading_summary_returns_warning_and_filters_non_paper_trades(tmp_path):
    db_path = str(tmp_path / "paper_summary.db")
    init_trade_tracking_db(db_path)
    paper_trade = _seed_paper_recommendation(db_path, ticker="AAPL", setup_type="momentum_breakout")
    log_trade_outcome(
        recommendation_id=paper_trade["id"],
        outcome="win",
        exit_price=110.0,
        realized_return=10.0,
        db_path=db_path,
    )

    log_recommendation(
        ticker="MSFT",
        asset_type="stock",
        direction="long",
        strategy="live_like_strategy",
        setup_type="trend_pullback",
        entry_price=100.0,
        target_price=108.0,
        stop_loss=95.0,
        risk_reward=1.6,
        db_path=db_path,
    )

    summary = get_paper_trading_summary(db_path=db_path)

    assert summary["ok"] is True
    assert summary["closed_paper_trades_count"] == 1
    assert summary["win_loss_record"]["total_recommendations"] == 1
    assert summary["best_setup_type"] == "momentum_breakout"
    assert "paper-trading" in summary["warning"].lower()


def test_review_paper_portfolio_handles_fresh_database_cleanly(monkeypatch, tmp_path):
    db_path = str(tmp_path / "paper_fresh.db")

    monkeypatch.setattr(
        "paper.paper_trader.monitor_open_trades",
        lambda update_outcomes=True, db_path="strategy_library.db": {
            "ok": True,
            "update_result": {"ok": True, "results": []},
            "open_recommendations": [],
            "errors": [],
        },
    )

    result = review_paper_portfolio(db_path=db_path)

    assert result["ok"] is True
    assert result["mode"] == "paper_trading"
    assert result["open_paper_trades"] == []
    assert result["win_loss_record"]["total_recommendations"] == 0
    assert "simulated" in result["warning"].lower()


def test_run_paper_trade_cycle_passes_option_flags(monkeypatch):
    captured = {}

    def fake_run_weekly_trade_hunt(**kwargs):
        captured.update(kwargs)
        return {
            "ok": True,
            "mode": "weekly_trade_hunt",
            "decision_result": {"final_recommendations": [], "logged_recommendations": []},
            "errors": [],
        }

    monkeypatch.setattr("paper.paper_trader.run_weekly_trade_hunt", fake_run_weekly_trade_hunt)

    result = run_paper_trade_cycle(
        include_market_regime=False,
        include_relative_strength=False,
        include_options=True,
        prefer_options=True,
        max_option_contracts_per_trade=2,
        include_portfolio_risk=False,
        include_position_sizing=False,
        include_memory_context=False,
        store_memory=True,
        account_size=25000.0,
        risk_mode="conservative",
    )

    assert result["ok"] is True
    assert captured["include_market_regime"] is False
    assert captured["include_relative_strength"] is False
    assert captured["include_options"] is True
    assert captured["prefer_options"] is True
    assert captured["max_option_contracts_per_trade"] == 2
    assert captured["include_portfolio_risk"] is False
    assert captured["include_position_sizing"] is False
    assert captured["include_memory_context"] is False
    assert captured["store_memory"] is True
    assert captured["account_size"] == 25000.0
    assert captured["risk_mode"] == "conservative"
