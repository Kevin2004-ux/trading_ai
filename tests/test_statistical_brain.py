from analytics.statistical_brain import (
    analyze_profile_performance,
    analyze_setup_performance,
    analyze_ticker_history,
    calculate_expectancy,
    enrich_candidate_with_statistics,
    score_statistical_confidence,
)
from tools.agent_tools import get_statistical_brain_tool
from tracking.trade_logger import init_trade_tracking_db, log_candidate_evaluation, log_recommendation, log_trade_outcome, log_scanner_run


def _seed_trade(
    db_path: str,
    *,
    ticker: str,
    strategy: str,
    setup_type: str,
    realized_return: float,
    outcome: str,
    scan_profile: str = "momentum_breakout",
):
    recommendation = log_recommendation(
        ticker=ticker,
        asset_type="stock",
        direction="long",
        strategy=strategy,
        entry_price=100.0,
        target_price=110.0,
        stop_loss=95.0,
        setup_type=setup_type,
        risk_reward=2.0,
        score=90.0,
        model_outputs_json={"scan_profile": scan_profile},
        db_path=db_path,
    )
    log_trade_outcome(
        recommendation_id=recommendation["id"],
        outcome=outcome,
        exit_price=100.0 * (1 + realized_return),
        realized_return=realized_return,
        max_gain=max(realized_return, 0.02),
        max_drawdown=min(realized_return, -0.01),
        grading_data_json={"scan_profile": scan_profile},
        db_path=db_path,
    )
    return recommendation


def _seed_candidate_evaluation(
    db_path: str,
    *,
    ticker: str,
    scan_profile: str,
    recommendation_status: str,
    score: float,
    risk_reward: float,
):
    scanner_run = log_scanner_run(universe="test", total_scanned=1, total_passed=0, total_rejected=0, db_path=db_path)
    log_candidate_evaluation(
        scanner_run_id=scanner_run["id"],
        ticker=ticker,
        asset_type="stock",
        direction="long",
        setup_type="momentum_breakout",
        passed_constraints=1 if recommendation_status in {"recommendable", "watchlist"} else 0,
        score=score,
        rejection_reason="" if recommendation_status != "rejected" else "Too weak",
        metrics_json={"risk_reward": risk_reward, "scan_profile": scan_profile},
        constraint_results_json={
            "recommendation_status": recommendation_status,
            "scan_profile": scan_profile,
        },
        db_path=db_path,
    )


def _seed_database(db_path: str):
    init_trade_tracking_db(db_path)
    _seed_trade(db_path, ticker="AAPL", strategy="strat_a", setup_type="momentum_breakout", realized_return=0.10, outcome="win")
    _seed_trade(db_path, ticker="AAPL", strategy="strat_a", setup_type="momentum_breakout", realized_return=-0.05, outcome="loss")
    _seed_trade(db_path, ticker="MSFT", strategy="strat_a", setup_type="momentum_breakout", realized_return=0.08, outcome="win")
    _seed_trade(db_path, ticker="NVDA", strategy="strat_b", setup_type="trend_pullback", realized_return=0.06, outcome="win", scan_profile="trend_pullback")
    _seed_trade(db_path, ticker="TSLA", strategy="strat_b", setup_type="trend_pullback", realized_return=-0.04, outcome="loss", scan_profile="trend_pullback")

    _seed_candidate_evaluation(db_path, ticker="AAPL", scan_profile="momentum_breakout", recommendation_status="recommendable", score=92.0, risk_reward=2.2)
    _seed_candidate_evaluation(db_path, ticker="MSFT", scan_profile="momentum_breakout", recommendation_status="watchlist", score=74.0, risk_reward=2.0)
    _seed_candidate_evaluation(db_path, ticker="TSLA", scan_profile="momentum_breakout", recommendation_status="rejected", score=40.0, risk_reward=1.5)
    _seed_candidate_evaluation(db_path, ticker="NVDA", scan_profile="trend_pullback", recommendation_status="recommendable", score=88.0, risk_reward=2.4)


def test_setup_performance_calculates_win_rate_correctly(tmp_path):
    db_path = str(tmp_path / "stats.db")
    _seed_database(db_path)

    result = analyze_setup_performance(db_path=db_path)

    assert result["ok"] is True
    breakout = next(group for group in result["groups"] if group["setup_type"] == "momentum_breakout")
    assert breakout["wins"] == 2
    assert breakout["losses"] == 1
    assert round(breakout["win_rate"], 4) == round(2 / 3, 4)


def test_expectancy_calculation_works():
    expectancy = calculate_expectancy(2, 1, 0.10, -0.05)

    assert round(expectancy, 4) == round((2 / 3) * 0.10 + (1 / 3) * -0.05, 4)


def test_confidence_is_low_for_small_sample_size():
    result = score_statistical_confidence(2, 0.5, 0.01)

    assert result["confidence_label"] == "low"


def test_confidence_improves_with_larger_sample_size():
    small = score_statistical_confidence(3, 0.6, 0.03)
    large = score_statistical_confidence(20, 0.6, 0.03)

    assert large["statistical_score"] > small["statistical_score"]
    assert large["confidence_label"] in {"medium", "high"}


def test_ticker_history_returns_correct_summary(tmp_path):
    db_path = str(tmp_path / "stats.db")
    _seed_database(db_path)

    result = analyze_ticker_history("AAPL", db_path=db_path)

    assert result["ok"] is True
    assert result["total_recommendations"] == 2
    assert result["wins"] == 1
    assert result["losses"] == 1
    assert result["most_common_setup_type"] == "momentum_breakout"


def test_candidate_enrichment_adds_statistical_context(tmp_path):
    db_path = str(tmp_path / "stats.db")
    _seed_database(db_path)

    candidate = {
        "ticker": "AAPL",
        "asset_type": "stock",
        "direction": "long",
        "setup_type": "momentum_breakout",
        "scan_profile": "momentum_breakout",
    }
    enriched = enrich_candidate_with_statistics(candidate, db_path=db_path)

    assert "statistical_context" in enriched
    assert "ticker_history" in enriched["statistical_context"]
    assert "setup_performance" in enriched["statistical_context"]


def test_get_statistical_brain_tool_returns_structured_data(tmp_path):
    db_path = str(tmp_path / "stats.db")
    _seed_database(db_path)

    result = get_statistical_brain_tool(
        ticker="AAPL",
        setup_type="momentum_breakout",
        scan_profile="momentum_breakout",
        db_path=db_path,
    )

    assert result["ok"] is True
    assert result["tool"] == "get_statistical_brain_tool"
    assert result["data"]["ticker_history"]["ticker"] == "AAPL"


def test_empty_database_returns_clean_no_data_response(tmp_path):
    db_path = str(tmp_path / "stats.db")
    init_trade_tracking_db(db_path)

    setup_result = analyze_setup_performance(db_path=db_path)
    ticker_result = analyze_ticker_history("AAPL", db_path=db_path)
    profile_result = analyze_profile_performance(db_path=db_path)

    assert setup_result["ok"] is True
    assert setup_result["groups"] == []
    assert ticker_result["ok"] is True
    assert ticker_result["total_recommendations"] == 0
    assert profile_result["ok"] is True
    assert profile_result["profiles"] == []
