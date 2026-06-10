import sqlite3

from tracking.trade_logger import (
    get_open_recommendations,
    get_recommendation,
    get_strategy_performance,
    get_win_loss_record,
    init_trade_tracking_db,
    log_candidate_evaluation,
    log_recommendation,
    log_scanner_run,
    log_trade_outcome,
    update_recommendation_status,
)


def test_init_trade_tracking_db_creates_tables(tmp_path):
    db_path = tmp_path / "trade_tracking.db"

    result = init_trade_tracking_db(str(db_path))

    assert result["ok"] is True

    with sqlite3.connect(db_path) as conn:
        table_names = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            ).fetchall()
        }

    assert "trade_recommendations" in table_names
    assert "scanner_runs" in table_names
    assert "candidate_evaluations" in table_names
    assert "trade_outcomes" in table_names


def test_trade_logger_workflow(tmp_path):
    db_path = str(tmp_path / "trade_tracking.db")
    init_trade_tracking_db(db_path)

    scanner_run = log_scanner_run(
        universe="AAPL,MSFT,NVDA",
        total_scanned=3,
        total_passed=1,
        total_rejected=2,
        market_data_freshness="2026-06-05T13:00:00Z",
        config_json={"min_rr": 2.0},
        db_path=db_path,
    )
    assert scanner_run["universe"] == "AAPL,MSFT,NVDA"
    assert scanner_run["config_json"]["min_rr"] == 2.0

    evaluation = log_candidate_evaluation(
        scanner_run_id=scanner_run["id"],
        ticker="AAPL",
        asset_type="equity",
        direction="long",
        setup_type="breakout",
        passed_constraints=True,
        score=92.5,
        rank=1,
        metrics_json={"rsi": 58.2},
        constraint_results_json={"passed": ["trend", "liquidity"]},
        db_path=db_path,
    )
    assert evaluation["passed_constraints"] == 1
    assert evaluation["metrics_json"]["rsi"] == 58.2

    recommendation = log_recommendation(
        ticker="AAPL",
        asset_type="equity",
        direction="long",
        strategy="swing_breakout_v1",
        setup_type="breakout",
        entry_price=100.0,
        target_price=110.0,
        stop_loss=95.0,
        risk_reward=2.0,
        confidence=0.8,
        score=92.5,
        thesis="Objective breakout passed all constraints.",
        invalidation="Close below support.",
        data_snapshot_json={"close": 100.0},
        constraint_results_json={"passed": True},
        model_outputs_json={"policy_action": "BUY"},
        db_path=db_path,
    )
    assert recommendation["ticker"] == "AAPL"
    assert recommendation["data_snapshot_json"]["close"] == 100.0
    assert recommendation["status"] == "open"

    fetched = get_recommendation(recommendation["id"], db_path=db_path)
    assert fetched is not None
    assert fetched["model_outputs_json"]["policy_action"] == "BUY"

    open_recommendations = get_open_recommendations(db_path=db_path)
    assert len(open_recommendations) == 1
    assert open_recommendations[0]["id"] == recommendation["id"]

    updated = update_recommendation_status(
        recommendation["id"],
        status="monitoring",
        notes="Watching follow-through.",
        db_path=db_path,
    )
    assert updated["status"] == "monitoring"
    assert "Watching follow-through." in updated["notes"]
    assert updated["closed_at"] is None

    still_open = get_open_recommendations(db_path=db_path)
    assert len(still_open) == 1
    assert still_open[0]["status"] == "monitoring"

    outcome = log_trade_outcome(
        recommendation_id=recommendation["id"],
        outcome="win",
        exit_price=108.0,
        exit_reason="target_hit",
        grading_data_json={"bars_held": 5},
        db_path=db_path,
    )
    assert outcome["outcome"] == "win"
    assert outcome["grading_data_json"]["bars_held"] == 5
    assert round(outcome["realized_return"], 2) == 8.0

    final_recommendation = get_recommendation(recommendation["id"], db_path=db_path)
    assert final_recommendation["status"] == "win"
    assert final_recommendation["outcome"] == "win"
    assert final_recommendation["exit_price"] == 108.0
    assert final_recommendation["closed_at"] is not None

    record = get_win_loss_record(db_path=db_path)
    assert record["wins"] == 1
    assert record["losses"] == 0
    assert record["win_rate"] == 100.0

    performance = get_strategy_performance(db_path=db_path)
    assert performance["overall"]["total_recommendations"] == 1
    assert performance["by_strategy"][0]["strategy"] == "swing_breakout_v1"
    assert round(performance["by_strategy"][0]["average_realized_return"], 2) == 8.0
