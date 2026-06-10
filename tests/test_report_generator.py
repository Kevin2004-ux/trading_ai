from reports.report_generator import (
    generate_full_paper_trading_report,
    generate_open_trade_review_report,
    generate_performance_report,
    generate_post_trade_review_report,
    generate_ticker_research_memo,
    generate_weekly_trade_plan_report,
)
from tracking.trade_logger import init_trade_tracking_db, log_recommendation, log_trade_outcome


def test_weekly_trade_plan_report_returns_markdown_with_selected_trades():
    result = generate_weekly_trade_plan_report(
        {
            "summary": {"message": "Weekly hunt complete."},
            "market_regime": {"regime": "risk_on_uptrend", "summary": "Risk on."},
            "portfolio_risk": {"risk_summary": {"message": "Portfolio risk check completed."}},
            "selection_result": {
                "watchlist_alternatives": [{"ticker": "MSFT", "rejection_reason": "Watchlist only"}],
                "rejected_candidates": [{"ticker": "TSLA", "rejection_reason": "Weak setup"}],
            },
            "decision_result": {
                "final_recommendations": [
                    {
                        "ticker": "AAPL",
                        "asset_type": "stock",
                        "direction": "long",
                        "setup_type": "momentum_breakout",
                        "entry_price": 100.0,
                        "target_price": 110.0,
                        "stop_loss": 95.0,
                        "risk_reward": 2.0,
                        "position_sizing": {"shares": 20},
                        "thesis": "Breakout with confirmation.",
                        "invalidation": "Close below 95.",
                        "risks": ["Earnings next month"],
                        "option_alternatives": [{"option_contract": "AAPL260703C00125000"}],
                    }
                ],
                "risk_rejected": [{"ticker": "NVDA", "rejection_reason": "Too much semiconductor concentration"}],
            },
        }
    )

    assert result["ok"] is True
    assert result["report_type"] == "weekly_trade_plan"
    assert "AAPL" in result["markdown"]
    assert "Option alternative" in result["markdown"]


def test_open_trade_review_report_includes_open_closed_and_manual_review_sections():
    result = generate_open_trade_review_report(
        {
            "open_paper_trades": [{"ticker": "AAPL", "status": "open", "entry_price": 100.0, "target_price": 110.0, "stop_loss": 95.0}],
            "recently_closed_paper_trades": [{"ticker": "MSFT", "outcome": "win", "exit_price": 108.0}],
            "win_loss_record": {"wins": 1, "losses": 0, "expired": 0, "open": 1, "win_rate": 100.0},
            "trade_review_summary": {"reviewed_count": 1, "skipped_count": 0},
            "monitoring_result": {"update_result": {"results": [{"ticker": "TSLA", "outcome": "manual_review", "exit_reason": "same_bar_ambiguity"}]}},
        }
    )

    assert result["ok"] is True
    assert "Open Trades" in result["markdown"]
    assert "Newly Closed Trades" in result["markdown"]
    assert "Manual Review Needed" in result["markdown"]


def test_performance_report_includes_win_rate_and_simulation_warning():
    result = generate_performance_report(
        {
            "win_loss_record": {"total_recommendations": 4, "closed_trades": 3, "open": 1, "wins": 2, "losses": 1, "win_rate": 66.67},
            "strategy_performance": {
                "by_strategy": [{"strategy": "breakout", "average_realized_return": 4.2}],
                "by_setup_type": [
                    {"setup_type": "momentum_breakout", "average_realized_return": 5.0},
                    {"setup_type": "pullback", "average_realized_return": -1.0},
                ],
            },
            "setup_performance": [{"setup_type": "momentum_breakout", "expectancy": 0.4}],
        }
    )

    assert result["ok"] is True
    assert "66.67" in result["markdown"]
    assert "simulated only" in result["markdown"].lower()


def test_ticker_research_memo_includes_bull_bear_and_evidence_table():
    result = generate_ticker_research_memo(
        {
            "ticker": "AAPL",
            "research_summary": "AAPL research summary.",
            "trade_thesis": {"thesis": "Constructive trend continuation."},
            "bull_case": {"points": ["Above 50-day moving average."]},
            "bear_case": {"points": ["Macro slowdown risk."]},
            "key_risks": ["Valuation risk"],
            "evidence_table": [{"category": "technical", "claim": "Trend intact", "source": "system"}],
            "research_conviction": {"label": "medium", "score": 68},
            "data_quality": {"missing_sections": [], "stale_data_flags": []},
        }
    )

    assert result["ok"] is True
    assert "Bull Case" in result["markdown"]
    assert "Bear Case" in result["markdown"]
    assert "Trend intact" in result["markdown"]


def test_post_trade_review_report_includes_lessons_and_trade_quality():
    result = generate_post_trade_review_report(
        [
            {
                "ticker": "AAPL",
                "outcome": "win",
                "trade_quality_label": "good_process",
                "thesis_validity": "valid",
                "review_summary": "Clean process win.",
                "lessons_json": [{"tag": "winner_followed_thesis"}],
                "mistakes_json": [],
                "strengths_json": ["Respected the plan."],
                "rule_adjustments_json": ["Keep current breakout filters."],
                "memory_status_json": {"ok": False, "source": "disabled"},
            }
        ]
    )

    assert result["ok"] is True
    assert "good_process" in result["markdown"]
    assert "winner_followed_thesis" in result["markdown"]


def test_full_paper_trading_report_returns_partial_report_cleanly_on_empty_db(tmp_path):
    db_path = str(tmp_path / "empty_reports.db")
    init_trade_tracking_db(db_path)

    result = generate_full_paper_trading_report(db_path=db_path)

    assert result["ok"] is True
    assert result["report_type"] == "full_paper_trading"
    assert "Open Recommendations" in result["markdown"]


def test_unsupported_format_returns_clean_error():
    result = generate_weekly_trade_plan_report({"decision_result": {}}, format="html")

    assert result["ok"] is False
    assert "Unsupported report format" in result["error"]


def test_full_paper_trading_report_can_include_real_rows(tmp_path):
    db_path = str(tmp_path / "full_report.db")
    init_trade_tracking_db(db_path)
    recommendation = log_recommendation(
        ticker="AAPL",
        asset_type="stock",
        direction="long",
        strategy="report_strategy",
        setup_type="momentum_breakout",
        entry_price=100.0,
        target_price=110.0,
        stop_loss=95.0,
        risk_reward=2.0,
        db_path=db_path,
        data_snapshot_json={"paper_trading": True, "execution_mode": "paper_trading"},
        model_outputs_json={"paper_trading": True, "execution_mode": "paper_trading"},
    )
    log_trade_outcome(
        recommendation_id=recommendation["id"],
        outcome="win",
        exit_price=108.0,
        db_path=db_path,
    )

    result = generate_full_paper_trading_report(db_path=db_path, format="dict")

    assert result["ok"] is True
    assert result["format"] == "dict"
    assert result["sections"]
