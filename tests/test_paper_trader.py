import sqlite3

from paper.paper_trader import (
    get_paper_risk_diagnostics,
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


def test_run_paper_trade_cycle_logs_only_valid_recommendations_and_labels_mode(monkeypatch, tmp_path):
    db_path = str(tmp_path / "paper_cycle_labels.db")
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
                                "model_outputs_json": {
                                    "paper_trading": True,
                                    "memory_context": {"retrieval_quality": {"quality_status": "warn"}},
                                },
                            }
                        },
                    }
                ],
            },
            "summary": {"memory_summary": {"enabled": True, "evaluated_count": 1}},
            "errors": [],
        },
    )

    result = run_paper_trade_cycle(db_path=db_path)

    assert result["ok"] is True
    assert result["mode"] == "paper_trading"
    assert result["run_id"]
    assert result["paper_trades_logged"][0]["ticker"] == "AAPL"
    assert result["paper_trades_logged"][0]["model_outputs_json"]["memory_context"]["retrieval_quality"]["quality_status"] == "warn"
    assert result["summary"]["memory_summary"]["evaluated_count"] == 1
    assert "simulated" in result["warning"].lower()


def test_run_paper_trade_cycle_returns_counts_when_no_trades_selected(monkeypatch, tmp_path):
    db_path = str(tmp_path / "paper_cycle_counts.db")
    monkeypatch.setattr(
        "paper.paper_trader.run_weekly_trade_hunt",
        lambda **kwargs: {
            "ok": True,
            "mode": "weekly_trade_hunt",
            "scan_result": {
                "rejected_candidates": [
                    {
                        "ticker": "BRK.B",
                        "rejection_reason": "symbol failure",
                        "data_quality": {"quality_label": "unavailable"},
                    }
                ],
                "data_quality_summary": {
                    "worst_quality_label": "unavailable",
                    "warnings": [],
                    "errors": ["symbol failure"],
                },
            },
            "decision_result": {
                "final_recommendations": [],
                "logged_recommendations": [],
            },
            "errors": [],
        },
    )

    result = run_paper_trade_cycle(db_path=db_path)

    assert result["ok"] is True
    assert result["summary"]["selected_count"] == 0
    assert result["summary"]["logged_count"] == 0
    assert result["summary"]["failed_ticker_count"] == 1
    assert result["summary"]["data_quality"]["worst_quality_label"] == "unavailable"


def test_run_paper_trade_cycle_includes_partial_async_scan_summary(monkeypatch, tmp_path):
    db_path = str(tmp_path / "paper_cycle_async.db")
    scan_execution_summary = {
        "total_tickers": 3,
        "completed_tickers": 1,
        "failed_tickers": ["BAD"],
        "timed_out_tickers": ["SLOW"],
        "partial_results_used": True,
        "duration_seconds": 15.0,
        "warnings": ["Scan completed with partial results due to timeout or provider failures."],
    }
    monkeypatch.setattr(
        "paper.paper_trader.run_weekly_trade_hunt",
        lambda **kwargs: {
            "ok": True,
            "mode": "weekly_trade_hunt",
            "scan_execution_summary": scan_execution_summary,
            "scan_result": {
                "rejected_candidates": [
                    {"ticker": "BAD", "data_quality": {"quality_label": "unavailable"}},
                    {"ticker": "SLOW", "data_quality": {"quality_label": "unavailable"}},
                ],
                "data_quality_summary": {"worst_quality_label": "unavailable"},
            },
            "decision_result": {
                "final_recommendations": [],
                "logged_recommendations": [],
            },
            "errors": ["Scan completed with partial results due to timeout or provider failures."],
        },
    )

    result = run_paper_trade_cycle(db_path=db_path)

    assert result["ok"] is True
    assert result["summary"]["failed_ticker_count"] == 2
    assert result["summary"]["timed_out_ticker_count"] == 1
    assert result["summary"]["scan_execution_summary"] == scan_execution_summary


def test_run_paper_trade_cycle_blocks_when_startup_validation_fails(monkeypatch, tmp_path):
    db_path = str(tmp_path / "paper_cycle_blocked.db")
    calls = {"hunt": 0}

    def fake_run_weekly_trade_hunt(**kwargs):
        calls["hunt"] += 1
        return {"ok": True}

    monkeypatch.setattr("paper.paper_trader.run_weekly_trade_hunt", fake_run_weekly_trade_hunt)

    result = run_paper_trade_cycle(
        db_path=db_path,
        startup_config={"IBKR_READ_ONLY": "false", "MARKET_DATA_PROVIDER": "ibkr"},
    )

    assert result["ok"] is False
    assert result["summary"]["selected_count"] == 0
    assert result["startup_readiness"]["readiness"] == "not_ready"
    assert calls["hunt"] == 0


def test_run_paper_trade_cycle_continues_with_startup_warnings(monkeypatch, tmp_path):
    db_path = str(tmp_path / "paper_cycle_warnings.db")
    monkeypatch.setattr(
        "paper.paper_trader.run_weekly_trade_hunt",
        lambda **kwargs: {
            "ok": True,
            "mode": "weekly_trade_hunt",
            "scan_result": {"rejected_candidates": [], "data_quality_summary": {}},
            "decision_result": {"final_recommendations": [], "logged_recommendations": []},
            "summary": {"selected_count": 0, "logged_count": 0},
            "errors": [],
        },
    )

    result = run_paper_trade_cycle(
        db_path=db_path,
        startup_config={"GEMINI_API_KEY": "", "ENABLE_GEMINI": "false"},
    )

    assert result["ok"] is True
    assert result["startup_readiness"]["ok"] is True
    assert result["startup_readiness"]["warnings"]


def test_run_paper_trade_cycle_creates_pipeline_checkpoints_and_audit_events(monkeypatch, tmp_path):
    db_path = str(tmp_path / "paper_cycle_observability.db")

    def fake_run_weekly_trade_hunt(**kwargs):
        return {
            "ok": True,
            "mode": "weekly_trade_hunt",
            "universe_result": {"ok": True, "universe": "mega_cap", "count": 1},
            "scan_execution_summary": {
                "total_tickers": 1,
                "completed_tickers": 1,
                "failed_tickers": [],
                "timed_out_tickers": [],
                "partial_results_used": False,
                "duration_seconds": 0.2,
            },
            "scan_result": {
                "data_quality_summary": {"worst_quality_label": "fresh"},
                "rejected_candidates": [],
            },
            "selection_result": {
                "selected_trades": [{"ticker": "AAPL", "recommendation_status": "recommendable"}],
                "watchlist_alternatives": [],
            },
            "macro_risk": {
                "ok": True,
                "macro_risk_level": "low",
                "risk_multiplier": 1.0,
                "new_trades_allowed": True,
                "warnings": [],
                "reasons": [],
            },
            "concentration_summary": {
                "ok": True,
                "snapshot": {"source": "latest_snapshot"},
                "evaluated_count": 1,
                "blocked_count": 0,
                "reduced_count": 0,
                "evaluations": [],
            },
            "technical_confirmation_summary": {
                "ok": True,
                "evaluated_count": 1,
                "rejected_count": 0,
                "warning_count": 0,
                "evaluations": [],
            },
            "filing_sentiment_summary": {
                "ok": True,
                "evaluated_count": 1,
                "filings_loaded_count": 1,
                "earnings_8k_count": 1,
                "blocking_count": 0,
                "high_risk_count": 0,
                "evaluations": [],
            },
            "research_risk_summary": {
                "ok": True,
                "evaluated_count": 1,
                "blocking_count": 0,
                "reduced_count": 1,
                "evaluations": [],
            },
            "decision_result": {
                "final_recommendations": [
                    {
                        "ticker": "AAPL",
                        "position_sizing": {"shares": 10},
                        "paper_fill": {"ok": True, "estimated_fill_price": 100.05},
                    }
                ],
                "logged_recommendations": [
                    {
                        "ok": True,
                        "data": {"recommendation": {"id": 1, "ticker": "AAPL"}},
                    }
                ],
            },
            "summary": {"selected_count": 1, "logged_count": 1},
            "errors": [],
        }

    monkeypatch.setattr("paper.paper_trader.run_weekly_trade_hunt", fake_run_weekly_trade_hunt)

    result = run_paper_trade_cycle(db_path=db_path)

    assert result["ok"] is True
    assert result["run_id"]
    assert result["pipeline_run"]["status"] == "completed"
    assert result["summary"]["pipeline_run_id"] == result["run_id"]
    assert result["checkpoint_summary"]["count"] >= 5
    assert result["audit_status"]["ok"] is True
    with sqlite3.connect(db_path) as conn:
        audit_events = {
            row[0]
            for row in conn.execute("SELECT event_type FROM audit_events WHERE run_id = ?", (result["run_id"],)).fetchall()
        }
    assert "paper_cycle_started" in audit_events
    assert "macro_risk_evaluated" in audit_events
    assert "correlation_snapshot_loaded" in audit_events
    assert "concentration_risk_evaluated" in audit_events
    assert "volume_profile_evaluated" in audit_events
    assert "timeframe_confirmation_evaluated" in audit_events
    assert "sec_filings_loaded" in audit_events
    assert "filing_analysis_completed" in audit_events
    assert "earnings_8k_analyzed" in audit_events
    assert "filing_sentiment_evaluated" in audit_events
    assert "short_interest_evaluated" in audit_events
    assert "borrow_pressure_evaluated" in audit_events
    assert "recent_news_loaded" in audit_events
    assert "news_sentiment_evaluated" in audit_events
    assert "iv_context_evaluated" in audit_events
    assert "greeks_evaluated" in audit_events
    assert "option_trade_risk_evaluated" in audit_events
    assert "option_strategies_built" in audit_events
    assert "option_strategy_evaluated" in audit_events
    assert "option_strategy_selected" in audit_events
    assert "candidate_selected" in audit_events
    assert "final_recommendation_logged" in audit_events
    assert "paper_cycle_completed" in audit_events


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


def test_get_paper_risk_diagnostics_returns_circuit_and_setup_decay(tmp_path):
    db_path = str(tmp_path / "paper_risk_diagnostics.db")
    init_trade_tracking_db(db_path)
    for index in range(7):
        recommendation = _seed_paper_recommendation(
            db_path,
            ticker=f"LOSS{index}",
            setup_type="momentum_breakout",
        )
        log_trade_outcome(
            recommendation_id=recommendation["id"],
            outcome="loss",
            exit_price=95.0,
            realized_return=-1.0,
            db_path=db_path,
        )

    diagnostics = get_paper_risk_diagnostics(db_path=db_path)

    assert diagnostics["ok"] is True
    assert diagnostics["mode"] == "paper_trading"
    assert diagnostics["closed_paper_trades_count"] == 7
    assert diagnostics["circuit_breaker"]["circuit_status"] == "blocked"
    assert "momentum_breakout" in diagnostics["setup_decay"]["setups"]
    assert diagnostics["warnings"]


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


def test_run_paper_trade_cycle_passes_option_flags(monkeypatch, tmp_path):
    db_path = str(tmp_path / "paper_cycle_flags.db")
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
        db_path=db_path,
        startup_config={"OPTION_QUOTES_VALIDATED": "true"},
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
