import sqlite3

from journal.trade_journal import (
    analyze_thesis_followthrough,
    build_trade_review,
    get_trade_reviews,
    identify_trade_lessons,
    init_trade_journal_db,
    log_trade_review,
    review_closed_trades,
    score_trade_quality,
)
from tracking.trade_logger import (
    get_recommendation,
    init_trade_tracking_db,
    log_recommendation,
    log_trade_outcome,
)


def _seed_recommendation(
    db_path: str,
    *,
    ticker: str = "AAPL",
    asset_type: str = "stock",
    thesis: str | None = "Breakout above resistance with strong relative strength.",
    invalidation: str | None = "Close below support or stop loss hit.",
    constraint_results: dict | None = None,
    model_outputs: dict | None = None,
    risk_reward: float = 2.5,
):
    return log_recommendation(
        ticker=ticker,
        asset_type=asset_type,
        direction="long",
        strategy="journal_strategy",
        setup_type="momentum_breakout",
        entry_price=100.0,
        target_price=112.5,
        stop_loss=95.0,
        risk_reward=risk_reward,
        score=88.0,
        thesis=thesis,
        invalidation=invalidation,
        constraint_results_json=constraint_results
        if constraint_results is not None
        else {"passed": True, "recommendation_status": "recommendable"},
        model_outputs_json=model_outputs
        if model_outputs is not None
        else {
            "position_sizing": {"shares": 20, "risk_amount": 100.0},
            "portfolio_risk": {"approved": True},
        },
        db_path=db_path,
    )


def test_init_trade_journal_db_creates_trade_reviews_table(tmp_path):
    db_path = str(tmp_path / "journal.db")

    result = init_trade_journal_db(db_path)

    assert result["ok"] is True
    with sqlite3.connect(db_path) as conn:
        table_names = {
            row[0]
            for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'").fetchall()
        }
    assert "trade_reviews" in table_names
    assert "trade_recommendations" in table_names


def test_build_trade_review_returns_full_schema_for_winning_good_process(tmp_path):
    db_path = str(tmp_path / "journal.db")
    init_trade_tracking_db(db_path)
    recommendation = _seed_recommendation(db_path)
    outcome = log_trade_outcome(
        recommendation_id=recommendation["id"],
        outcome="win",
        exit_price=112.5,
        exit_reason="target_hit",
        max_gain=0.13,
        max_drawdown=-0.01,
        db_path=db_path,
    )
    recommendation = get_recommendation(recommendation["id"], db_path=db_path)

    review = build_trade_review(recommendation, outcome=outcome, db_path=db_path)

    assert review["ok"] is True
    assert review["recommendation_id"] == recommendation["id"]
    assert review["ticker"] == "AAPL"
    assert review["outcome"] == "win"
    assert review["trade_quality"]["label"] == "good_process"
    assert review["trade_quality"]["score"] >= 75
    assert review["thesis_analysis"]["thesis_validity"] == "valid"
    assert any(lesson["tag"] == "winner_followed_thesis" for lesson in review["lessons"])
    assert "data_quality" in review
    assert review["error"] is None


def test_losing_trade_with_good_risk_control_is_not_automatically_bad(tmp_path):
    db_path = str(tmp_path / "journal.db")
    init_trade_tracking_db(db_path)
    recommendation = _seed_recommendation(db_path)
    outcome = log_trade_outcome(
        recommendation_id=recommendation["id"],
        outcome="loss",
        exit_price=95.0,
        exit_reason="stop_loss_hit",
        max_gain=0.03,
        max_drawdown=-0.05,
        db_path=db_path,
    )
    recommendation = get_recommendation(recommendation["id"], db_path=db_path)

    thesis_analysis = analyze_thesis_followthrough(recommendation, outcome=outcome)
    quality = score_trade_quality(recommendation, outcome=outcome, thesis_analysis=thesis_analysis)
    lessons = identify_trade_lessons(recommendation, outcome=outcome, thesis_analysis=thesis_analysis)

    assert quality["label"] in {"good_process", "mixed_process"}
    assert any("Loss appears" in driver for driver in quality["drivers"])
    assert any(lesson["tag"] == "valid_loss_with_plan" for lesson in lessons["lessons"])


def test_missing_thesis_creates_data_quality_warning(tmp_path):
    db_path = str(tmp_path / "journal.db")
    init_trade_tracking_db(db_path)
    recommendation = _seed_recommendation(db_path, thesis=None)
    outcome = log_trade_outcome(
        recommendation_id=recommendation["id"],
        outcome="win",
        exit_price=112.5,
        exit_reason="target_hit",
        db_path=db_path,
    )
    recommendation = get_recommendation(recommendation["id"], db_path=db_path)

    review = build_trade_review(recommendation, outcome=outcome, db_path=db_path)

    assert "thesis" in review["data_quality"]["missing_sections"]
    assert review["thesis_analysis"]["thesis_validity"] == "unknown"
    assert any(lesson["tag"] == "insufficient_data_to_review" for lesson in review["lessons"])


def test_failed_constraint_trade_is_penalized(tmp_path):
    db_path = str(tmp_path / "journal.db")
    init_trade_tracking_db(db_path)
    recommendation = _seed_recommendation(
        db_path,
        constraint_results={"passed": False, "recommendation_status": "rejected"},
    )
    outcome = log_trade_outcome(
        recommendation_id=recommendation["id"],
        outcome="loss",
        exit_price=95.0,
        exit_reason="stop_loss_hit",
        db_path=db_path,
    )
    recommendation = get_recommendation(recommendation["id"], db_path=db_path)

    review = build_trade_review(recommendation, outcome=outcome, db_path=db_path)

    assert any("Failed or watchlist constraints" in penalty for penalty in review["trade_quality"]["penalties"])
    assert review["trade_quality"]["score"] < 75


def test_option_trade_missing_liquidity_context_creates_warning(tmp_path):
    db_path = str(tmp_path / "journal.db")
    init_trade_tracking_db(db_path)
    recommendation = _seed_recommendation(
        db_path,
        asset_type="option",
        model_outputs={"position_sizing": {"contracts": 1}, "portfolio_risk": {"approved": True}},
    )
    outcome = log_trade_outcome(
        recommendation_id=recommendation["id"],
        outcome="manual_review",
        exit_reason="option_expired_without_option_price_history",
        db_path=db_path,
    )
    recommendation = get_recommendation(recommendation["id"], db_path=db_path)

    review = build_trade_review(recommendation, outcome=outcome, db_path=db_path)

    assert any(lesson["tag"] == "option_liquidity_risk" for lesson in review["lessons"])
    assert any("Option trade is missing liquidity context" in penalty for penalty in review["trade_quality"]["penalties"])


def test_log_trade_review_and_get_trade_reviews_filters(tmp_path):
    db_path = str(tmp_path / "journal.db")
    init_trade_tracking_db(db_path)
    recommendation = _seed_recommendation(db_path, ticker="MSFT")
    outcome = log_trade_outcome(
        recommendation_id=recommendation["id"],
        outcome="win",
        exit_price=112.5,
        exit_reason="target_hit",
        db_path=db_path,
    )
    recommendation = get_recommendation(recommendation["id"], db_path=db_path)
    review = build_trade_review(recommendation, outcome=outcome, db_path=db_path)

    logged = log_trade_review(recommendation["id"], review, db_path=db_path)
    by_id = get_trade_reviews(recommendation_id=recommendation["id"], db_path=db_path)
    by_ticker = get_trade_reviews(ticker="MSFT", db_path=db_path)

    assert logged["ok"] is True
    assert logged["review"]["lessons_json"][0]["tag"] == "winner_followed_thesis"
    assert by_id["count"] == 1
    assert by_id["reviews"][0]["recommendation_id"] == recommendation["id"]
    assert by_ticker["count"] == 1
    assert by_ticker["reviews"][0]["ticker"] == "MSFT"


def test_review_closed_trades_skips_already_reviewed_and_memory_failure_is_non_blocking(monkeypatch, tmp_path):
    db_path = str(tmp_path / "journal.db")
    init_trade_tracking_db(db_path)
    recommendation = _seed_recommendation(db_path)
    log_trade_outcome(
        recommendation_id=recommendation["id"],
        outcome="win",
        exit_price=112.5,
        exit_reason="target_hit",
        db_path=db_path,
    )

    monkeypatch.setattr(
        "journal.trade_journal.store_memory_item",
        lambda *args, **kwargs: {
            "ok": False,
            "source": "unavailable",
            "error": "Pinecone is not configured.",
        },
    )

    first = review_closed_trades(db_path=db_path, store_memory=True)
    second = review_closed_trades(db_path=db_path, store_memory=True)

    assert first["ok"] is True
    assert first["reviewed_count"] == 1
    assert first["reviews"][0]["memory_status_json"]["ok"] is False
    assert second["ok"] is True
    assert second["reviewed_count"] == 0
    assert second["skipped_count"] == 0
