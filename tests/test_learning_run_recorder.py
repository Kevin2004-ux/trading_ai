import sqlite3

import planning.plan_executor as plan_executor
from learning import get_snapshot_counts, record_research_execution


def _candidate(ticker="AAPL", status="watchlist", score=80):
    return {
        "ticker": ticker,
        "asset_type": "stock",
        "status": status,
        "recommendation_status": status,
        "rank": 1,
        "score": score,
        "engine_score": score,
        "opportunity_score": score,
        "opportunity_score_version": "stock_opportunity_v1",
        "opportunity_components": {"engine_core": {"score": score, "weight": 1, "available": True}},
        "data_confidence": 90,
        "entry_price": 100,
        "target_price": 110,
        "stop_loss": 95,
        "risk_reward": 2.0,
        "data_quality": {"ok": True, "quality_label": "good"},
        "raw_candidate": {
            "ticker": ticker,
            "asset_type": "stock",
            "recommendation_status": status,
            "current_price": 100,
            "entry_price": 100,
            "target_price": 110,
            "stop_loss": 95,
            "risk_reward": 2.0,
            "technical_snapshot": {"current_price": 100, "sma_20": 98},
            "data_quality": {"ok": True, "quality_label": "good"},
        },
    }


def _provider_failure(ticker="MSFT"):
    return {
        "ticker": ticker,
        "asset_type": "stock",
        "recommendation_status": "rejected",
        "current_price": None,
        "failed_constraints": ["scanner_error"],
        "data_quality": {"ok": False, "quality_label": "unavailable"},
        "rejection_reason": "IBKR/TWS is not reachable on 127.0.0.1:7496.",
    }


def _execution_result(candidate=None, failure=None):
    return {
        "ok": True,
        "run_id": "run-1",
        "approved_plan": {
            "request_id": "req-1",
            "plan_version": "scan_plan_v1",
            "requested_instrument": "stocks",
            "objective": "best_ideas",
            "include_options": False,
        },
        "execution_summary": {"status": "completed", "include_options": False},
        "best_available_ideas": {
            "ok": True,
            "ranking_status": "available" if candidate else "unavailable",
            "paper_eligible": [],
            "stock_watchlist": [candidate] if candidate else [],
            "option_research_only": [],
            "blocked_but_interesting": [failure] if failure else [],
            "option_underlying_watchlist": [],
            "data_missing": ["Scanner/provider failures returned no usable market data."] if failure else [],
            "system_issues": ["IBKR/TWS is not reachable on 127.0.0.1:7496."] if failure else [],
            "warnings": [],
        },
        "assistant_response": {"market_state": {"provider_status": "available" if candidate else "unavailable"}},
    }


def test_research_run_recording_creates_normalized_snapshot(tmp_path):
    db_path = str(tmp_path / "recording.db")

    result = record_research_execution(_execution_result(candidate=_candidate()), db_path=db_path)
    counts = get_snapshot_counts(db_path)

    assert result["ok"] is True
    assert result["records_created"] == 1
    assert result["candidate_snapshots_created"] == 1
    assert counts["candidate_snapshot_count"] == 1
    with sqlite3.connect(db_path) as conn:
        row = conn.execute("SELECT ticker, actionability_status, opportunity_score FROM candidate_snapshots").fetchone()
    assert row == ("AAPL", "watchlist", 80.0)


def test_provider_failures_do_not_become_learnable_candidates(tmp_path):
    db_path = str(tmp_path / "provider_failure.db")

    result = record_research_execution(_execution_result(failure=_provider_failure()), db_path=db_path)

    assert result["ok"] is True
    assert result["records_created"] == 1
    assert result["candidate_snapshots_created"] == 0
    with sqlite3.connect(db_path) as conn:
        assert conn.execute("SELECT COUNT(*) FROM candidate_snapshots").fetchone()[0] == 0


def test_candidate_snapshots_are_immutable_across_repeated_recordings(tmp_path):
    db_path = str(tmp_path / "immutable.db")

    record_research_execution(_execution_result(candidate=_candidate("AAPL", score=70)), db_path=db_path)
    record_research_execution(_execution_result(candidate=_candidate("AAPL", score=90)), db_path=db_path)

    with sqlite3.connect(db_path) as conn:
        rows = conn.execute("SELECT ticker, opportunity_score FROM candidate_snapshots ORDER BY id").fetchall()
    assert rows == [("AAPL", 70.0), ("AAPL", 90.0)]


def test_recording_failure_does_not_break_scan(monkeypatch, tmp_path):
    db_path = str(tmp_path / "scan.db")

    def fake_hunt(**kwargs):
        return {
            "ok": True,
            "decision_result": {"final_recommendations": [], "logged_recommendations": []},
            "selection_result": {"watchlist_alternatives": [_candidate("AAPL")], "rejected_candidates": []},
            "scan_result": {"watchlist_candidates": [_candidate("AAPL")], "rejected_candidates": []},
            "summary": {"profiles_run": [], "logged_count": 0},
            "errors": [],
        }

    monkeypatch.setattr(plan_executor, "run_weekly_trade_hunt", fake_hunt)
    monkeypatch.setattr(plan_executor, "record_research_execution", lambda *args, **kwargs: {"ok": False, "warnings": ["boom"], "errors": ["boom"]})

    result = plan_executor.execute_scan_plan({"requested_instrument": "stocks", "max_tickers": 1}, db_path=db_path)

    assert result["ok"] is True
    assert "boom" in result["warnings"]
    assert result["trading_result"]["decision_result"]["logged_recommendations"] == []
