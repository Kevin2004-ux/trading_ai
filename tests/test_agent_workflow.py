import importlib
import importlib.util
import sqlite3
from pathlib import Path

from tools.agent_tools import (
    get_open_recommendations_tool,
    get_statistical_brain_tool,
    get_strategy_performance_tool,
    get_win_loss_record_tool,
    log_recommendation_tool,
    scan_market_for_weekly_trades_tool,
    update_outcomes_tool,
)
from tracking.trade_logger import get_recommendation, init_trade_tracking_db
from translator.prompts import SYSTEM_PROMPT


def _load_statistical_seed_database():
    module_path = Path(__file__).with_name("test_statistical_brain.py")
    spec = importlib.util.spec_from_file_location("local_test_statistical_brain", module_path)
    module = importlib.util.module_from_spec(spec)
    assert spec is not None and spec.loader is not None
    spec.loader.exec_module(module)
    return module._seed_database


def _recommendable_constraints(score: float = 91.5) -> dict:
    return {
        "passed": True,
        "recommendation_status": "recommendable",
        "score": score,
        "constraint_results": {},
        "failed_constraints": [],
        "rejection_reason": "",
        "config": {"minimum_risk_reward": 2.0},
    }


def _mock_market_snapshot(
    *,
    ticker: str,
    current_price: float,
    sma_20: float,
    sma_50: float,
    high_20: float,
    atr_14: float,
    average_volume_20: float,
    relative_volume: float,
    atr_percent: float,
    daily_return: float,
):
    return {
        "ok": True,
        "ticker": ticker,
        "source": "polygon",
        "timestamp": "2026-06-05T00:00:00+00:00",
        "data": {
            "quote": {"last_price": current_price},
            "technical_snapshot": {
                "ok": True,
                "current_price": current_price,
                "previous_close": round(current_price / (1 + daily_return / 100.0), 4) if daily_return != -100 else current_price,
                "daily_return": daily_return,
                "sma_20": sma_20,
                "sma_50": sma_50,
                "sma_200": sma_50 - 3.0,
                "high_20": high_20,
                "low_20": current_price - 8.0,
                "atr_14": atr_14,
                "atr_percent": atr_percent,
                "average_volume_20": average_volume_20,
                "relative_volume": relative_volume,
                "rsi_14": 58.0,
                "macd": 1.2,
                "distance_from_20_sma": ((current_price - sma_20) / sma_20) * 100.0 if sma_20 else None,
                "distance_from_50_sma": ((current_price - sma_50) / sma_50) * 100.0 if sma_50 else None,
            },
            "data_freshness": {
                "ok": True,
                "latest_bar_timestamp": "2026-06-05T00:00:00+00:00",
                "age_days": 0,
                "is_stale": False,
                "freshness_label": "fresh",
            },
        },
        "error": None,
    }


def _workflow_scan_setup(monkeypatch):
    monkeypatch.setattr(
        "tools.agent_tools.get_default_universe",
        lambda universe="large_cap", max_tickers=500: {
            "ok": True,
            "universe": universe,
            "timestamp": "2026-06-05T00:00:00+00:00",
            "tickers": ["AAPL", "MSFT", "TSLA"],
            "count": 3,
            "source": "static_curated",
            "max_tickers": max_tickers,
            "errors": [],
        },
    )

    snapshots = {
        "AAPL": _mock_market_snapshot(
            ticker="AAPL",
            current_price=120.0,
            sma_20=119.0,
            sma_50=118.0,
            high_20=121.0,
            atr_14=2.0,
            average_volume_20=2_500_000,
            relative_volume=1.9,
            atr_percent=1.7,
            daily_return=1.6,
        ),
        "MSFT": _mock_market_snapshot(
            ticker="MSFT",
            current_price=100.0,
            sma_20=99.7,
            sma_50=99.4,
            high_20=101.2,
            atr_14=1.2,
            average_volume_20=1_100_000,
            relative_volume=1.2,
            atr_percent=2.0,
            daily_return=0.2,
        ),
        "TSLA": _mock_market_snapshot(
            ticker="TSLA",
            current_price=80.0,
            sma_20=83.0,
            sma_50=85.0,
            high_20=86.0,
            atr_14=1.5,
            average_volume_20=900_000,
            relative_volume=0.8,
            atr_percent=1.8,
            daily_return=-1.7,
        ),
    }

    monkeypatch.setattr(
        "scanner.swing_scanner.get_market_snapshot",
        lambda ticker, lookback_days=180: snapshots[ticker],
    )


def test_weekly_scan_flow_dry_run(monkeypatch, tmp_path):
    db_path = str(tmp_path / "workflow_scan.db")
    init_trade_tracking_db(db_path)
    _workflow_scan_setup(monkeypatch)

    result = scan_market_for_weekly_trades_tool(
        universe="large_cap",
        profiles=["momentum_breakout"],
        db_path=db_path,
    )

    assert result["ok"] is True
    assert result["tool"] == "scan_market_for_weekly_trades_tool"
    assert isinstance(result["timestamp"], str)
    assert result["error"] is None

    data = result["data"]
    assert "universe_result" in data
    assert "scan_result" in data
    assert "selection_result" in data

    selection_result = data["selection_result"]
    scan_result = data["scan_result"]

    assert len(selection_result["selected_trades"]) <= 5
    assert all(candidate["recommendation_status"] == "recommendable" for candidate in selection_result["selected_trades"])
    assert "MSFT" not in {candidate["ticker"] for candidate in selection_result["selected_trades"]}
    assert any(candidate["ticker"] == "TSLA" for candidate in scan_result["rejected_candidates"])
    assert any(candidate["ticker"] == "MSFT" for candidate in scan_result["watchlist_candidates"])

    open_recommendations = get_open_recommendations_tool(db_path=db_path)
    assert open_recommendations["ok"] is True
    assert open_recommendations["data"]["recommendations"] == []


def test_final_recommendation_logging_flow(monkeypatch, tmp_path):
    db_path = str(tmp_path / "workflow_logging.db")
    init_trade_tracking_db(db_path)
    _workflow_scan_setup(monkeypatch)

    scan_result = scan_market_for_weekly_trades_tool(
        universe="large_cap",
        profiles=["momentum_breakout"],
        db_path=db_path,
    )
    selected_candidate = scan_result["data"]["selection_result"]["selected_trades"][0]

    logged = log_recommendation_tool(
        ticker=selected_candidate["ticker"],
        asset_type=selected_candidate["asset_type"],
        direction=selected_candidate["direction"],
        strategy="weekly_selector_v1",
        entry_price=selected_candidate["entry_price"],
        target_price=selected_candidate["target_price"],
        stop_loss=selected_candidate["stop_loss"],
        setup_type=selected_candidate["setup_type"],
        risk_reward=selected_candidate["risk_reward"],
        holding_period_days=7,
        confidence=0.8,
        score=selected_candidate["score"],
        thesis="Passed objective scanner, constraint, and weekly selection rules.",
        invalidation="Exit if stop loss is hit or the setup deteriorates.",
        data_snapshot={"selected_profile": selected_candidate.get("selected_profile")},
        constraint_results={
            "passed": True,
            "recommendation_status": "recommendable",
            "score": selected_candidate["score"],
            "constraint_results": selected_candidate.get("constraint_results", {}),
            "failed_constraints": [],
            "rejection_reason": "",
            "config": {"minimum_risk_reward": 2.0},
        },
        model_outputs={"scan_profile": selected_candidate.get("scan_profile")},
        db_path=db_path,
    )

    assert logged["ok"] is True
    recommendation_id = logged["data"]["recommendation_id"]
    assert recommendation_id is not None

    fetched = get_recommendation(recommendation_id, db_path=db_path)
    assert fetched["ticker"] == selected_candidate["ticker"]

    open_recommendations = get_open_recommendations_tool(db_path=db_path)
    assert any(rec["id"] == recommendation_id for rec in open_recommendations["data"]["recommendations"])


def test_failed_or_watchlist_candidates_cannot_be_logged(tmp_path):
    db_path = str(tmp_path / "workflow_rejects.db")
    init_trade_tracking_db(db_path)

    watchlist_attempt = log_recommendation_tool(
        ticker="MSFT",
        asset_type="stock",
        direction="long",
        strategy="weekly_selector_v1",
        entry_price=100.0,
        target_price=103.0,
        stop_loss=98.5,
        risk_reward=2.0,
        constraint_results={
            "passed": True,
            "recommendation_status": "watchlist",
            "score": 77.0,
            "constraint_results": {},
            "failed_constraints": [],
            "rejection_reason": "",
            "config": {"minimum_risk_reward": 2.0},
        },
        db_path=db_path,
    )
    failed_attempt = log_recommendation_tool(
        ticker="TSLA",
        asset_type="stock",
        direction="long",
        strategy="weekly_selector_v1",
        entry_price=80.0,
        target_price=84.0,
        stop_loss=78.0,
        risk_reward=2.0,
        constraint_results={
            "passed": False,
            "recommendation_status": "rejected",
            "score": 40.0,
            "constraint_results": {},
            "failed_constraints": ["minimum_relative_volume"],
            "rejection_reason": "Failed liquidity rule.",
            "config": {"minimum_risk_reward": 2.0},
        },
        db_path=db_path,
    )

    assert watchlist_attempt["ok"] is False
    assert failed_attempt["ok"] is False

    with sqlite3.connect(db_path) as conn:
        recommendation_count = conn.execute("SELECT COUNT(*) FROM trade_recommendations").fetchone()[0]
    assert recommendation_count == 0


def test_outcome_update_flow_dry_run(monkeypatch, tmp_path):
    db_path = str(tmp_path / "workflow_outcomes.db")
    init_trade_tracking_db(db_path)
    monkeypatch.setattr(
        "tracking.trade_logger._utc_now_iso",
        lambda: "2026-06-05T00:00:00+00:00",
    )

    logged = log_recommendation_tool(
        ticker="AAPL",
        asset_type="stock",
        direction="long",
        strategy="weekly_selector_v1",
        entry_price=100.0,
        target_price=110.0,
        stop_loss=95.0,
        setup_type="momentum_breakout",
        risk_reward=2.0,
        holding_period_days=5,
        thesis="Objective rules passed.",
        invalidation="Stop loss hit.",
        constraint_results=_recommendable_constraints(),
        db_path=db_path,
    )

    bars = [
        {"timestamp": "2026-06-06T00:00:00+00:00", "open": 100.0, "high": 106.0, "low": 99.0, "close": 105.0, "volume": 1000},
        {"timestamp": "2026-06-07T00:00:00+00:00", "open": 105.0, "high": 111.0, "low": 104.0, "close": 110.0, "volume": 1000},
    ]
    monkeypatch.setattr(
        "tracking.outcome_grader.get_historical_bars",
        lambda ticker, lookback_days=180: {
            "ok": True,
            "ticker": ticker,
            "source": "polygon",
            "timestamp": "2026-06-05T00:00:00+00:00",
            "data": {"bars": bars},
            "error": None,
        },
    )
    monkeypatch.setattr(
        "tracking.outcome_grader._now_utc",
        lambda: importlib.import_module("pandas").Timestamp("2026-06-07T00:00:00+00:00").to_pydatetime(),
    )

    update_result = update_outcomes_tool(db_path=db_path)

    assert update_result["ok"] is True
    assert update_result["data"]["updated"] == 1
    assert update_result["data"]["results"][0]["outcome"] == "win"

    updated_recommendation = get_recommendation(logged["data"]["recommendation_id"], db_path=db_path)
    assert updated_recommendation["status"] == "win"
    assert updated_recommendation["outcome"] == "win"

    with sqlite3.connect(db_path) as conn:
        trade_outcome_count = conn.execute("SELECT COUNT(*) FROM trade_outcomes").fetchone()[0]
    assert trade_outcome_count == 1

    win_loss_record = get_win_loss_record_tool(db_path=db_path)
    assert win_loss_record["ok"] is True
    assert win_loss_record["data"]["wins"] == 1


def test_performance_and_statistical_brain_flow(tmp_path):
    db_path = str(tmp_path / "workflow_stats.db")
    _seed_database = _load_statistical_seed_database()
    _seed_database(db_path)

    win_loss_record = get_win_loss_record_tool(db_path=db_path)
    strategy_performance = get_strategy_performance_tool(db_path=db_path)
    statistical_brain = get_statistical_brain_tool(
        ticker="AAPL",
        setup_type="momentum_breakout",
        scan_profile="momentum_breakout",
        db_path=db_path,
    )

    for result in (win_loss_record, strategy_performance, statistical_brain):
        assert result["ok"] is True
        assert isinstance(result["tool"], str)
        assert isinstance(result["timestamp"], str)
        assert result["data"] is not None
        assert result["error"] is None

    assert win_loss_record["data"]["win_rate"] is not None
    assert strategy_performance["data"]["overall"]["total_recommendations"] >= 1
    assert statistical_brain["data"]["setup_performance"]
    assert statistical_brain["data"]["ticker_history"]["ticker"] == "AAPL"
    assert statistical_brain["data"]["profile_performance"]


def test_translator_import_and_unavailable_gemini_behavior(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    translator_main = importlib.reload(importlib.import_module("translator.main"))

    response = translator_main.ask_translator("Find trades this week")

    assert callable(translator_main.ask_translator)
    assert "unavailable" in response.lower()


def test_prompt_guardrails_for_full_workflow():
    prompt = SYSTEM_PROMPT

    assert "Objective tools are the source of truth." in prompt
    assert "`scan_market_for_weekly_trades_tool`" in prompt
    assert "`log_recommendation_tool`" in prompt
    assert "Never recommend a trade that failed constraints." in prompt
    assert "Never recommend a watchlist candidate as a final trade." in prompt
    assert "Do not claim certainty." in prompt
    assert "You are not a financial advisor." in prompt
