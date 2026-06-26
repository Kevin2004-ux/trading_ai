import sqlite3
import json
import time

import pytest

from agent.trading_brain import (
    build_trade_decision,
    monitor_open_trades,
    review_ticker_opportunity,
    run_weekly_trade_hunt,
)
from tools.agent_tools import log_recommendation_tool
from tracking.trade_logger import init_trade_tracking_db
from memory.annotation_store import add_human_annotation


@pytest.fixture(autouse=True)
def _default_low_macro_risk(monkeypatch):
    monkeypatch.setattr(
        "agent.trading_brain.evaluate_macro_risk",
        lambda: {
            "ok": True,
            "macro_risk_level": "low",
            "risk_multiplier": 1.0,
            "new_trades_allowed": True,
            "warnings": [],
            "reasons": [],
        },
    )


def _candidate(
    ticker: str,
    *,
    recommendation_status: str = "recommendable",
    passed: bool = True,
    risk_reward: float = 2.5,
    entry_price: float = 100.0,
    target_price: float = 110.0,
    stop_loss: float = 95.0,
    score: float = 91.0,
) -> dict:
    return {
        "ticker": ticker,
        "asset_type": "stock",
        "direction": "long",
        "setup_type": "momentum_breakout",
        "scan_profile": "momentum_breakout",
        "selected_profile": "momentum_breakout",
        "quality_bucket": "A",
        "score": score,
        "entry_price": entry_price,
        "target_price": target_price,
        "stop_loss": stop_loss,
        "risk_reward": risk_reward,
        "holding_period_days": 7,
        "recommendation_status": recommendation_status,
        "passed": passed,
        "constraint_results": {"minimum_risk_reward": {"passed": passed}},
        "failed_constraints": [] if passed else ["minimum_risk_reward"],
        "rejection_reason": "" if passed else "Constraint failure.",
        "why_this_profile_matched": ["Relative volume confirms participation."],
        "technical_snapshot": {"current_price": entry_price, "relative_volume": 1.8},
        "statistical_context": {
            "setup_performance": {"expectancy": 0.05, "meets_min_sample_size": True},
            "ticker_history": {"historical_edge": "positive", "closed_trades": 8},
            "profile_performance": {"avg_realized_return": 0.03, "meets_min_sample_size": True},
            "statistical_score": 82.0,
            "confidence_label": "high",
            "warnings": [],
        },
        "catalyst_context": {
            "catalyst_label": "positive",
            "positive_catalysts": ["Analyst upgrade"],
            "negative_catalysts": [],
            "risk_flags": [],
            "catalyst_bias": 4.0,
        },
        "relative_strength_context": {
            "ok": True,
            "relative_strength_label": "outperforming",
            "relative_strength_score": 76.0,
            "risk_flags": [],
            "summary": "Outperforming benchmarks.",
        },
    }


def _selection_result(*candidates: dict) -> dict:
    return {
        "ok": True,
        "timestamp": "2026-06-05T00:00:00+00:00",
        "selected_trades": list(candidates),
        "watchlist_alternatives": [_candidate("MSFT", recommendation_status="watchlist", score=74.0)],
        "rejected_for_portfolio_limits": [],
        "selection_summary": {
            "max_trades": 5,
            "min_trades": 2,
            "selected_count": len(candidates),
            "watchlist_count": 1,
            "message": "Mock selection completed.",
        },
        "errors": [],
    }


def _option_candidate(
    contract: str = "AAPL260703C00125000",
    *,
    passed: bool = True,
    recommendation_status: str = "recommendable",
    option_contract: str | None = None,
    expiration: str | None = "2026-07-03",
    risk_reward: float = 2.6,
    score: float = 90.0,
    breakeven_realistic: bool = True,
    **overrides,
) -> dict:
    resolved_contract = option_contract if option_contract is not None else contract
    candidate = {
        "ticker": resolved_contract,
        "underlying_ticker": "AAPL",
        "option_contract": resolved_contract,
        "option_type": "call",
        "expiration": expiration,
        "days_to_expiration": 25,
        "bid": 3.8,
        "ask": 4.0,
        "mid": 3.9,
        "open_interest": 1600,
        "volume": 450,
        "implied_volatility": 0.28,
        "iv_rank": 18,
        "delta": 0.52,
        "gamma": 0.04,
        "theta": -0.04,
        "vega": 0.12,
        "spread_percent": 0.05,
        "risk_reward": risk_reward,
        "score": score,
        "passed": passed,
        "recommendation_status": recommendation_status,
        "constraint_results": {"pricing_available": {"passed": passed}},
        "failed_constraints": [] if passed else ["minimum_volume"],
        "rejection_reason": "" if passed else "Rejected option.",
        "breakeven_realistic": breakeven_realistic,
        "expected_value_at_target": 18.0,
        "expected_value_at_stop": 0.0,
        "mispricing_label": "attractive_value",
        "mispricing_score": 82.0,
        "mispricing_context": {
            "ok": True,
            "mispricing_label": "attractive_value",
            "mispricing_score": 82.0,
            "target_exceeds_breakeven": True,
            "warnings": [],
            "explanation": "Attractive research value.",
        },
        "iv_context": {
            "ok": True,
            "current_iv": 0.28,
            "iv_rank": 18,
            "iv_percentile": 22,
            "iv_context": "cheap",
            "trade_bias": "long_premium_favorable",
            "warnings": [],
            "errors": [],
        },
        "greeks_monitoring": {
            "ok": True,
            "contract": resolved_contract,
            "delta": 0.52,
            "gamma": 0.04,
            "theta": -0.04,
            "vega": 0.12,
            "rho": None,
            "greeks_quality": "good",
            "risk_level": "low",
            "warnings": [],
            "errors": [],
        },
        "option_trade_risk": {
            "ok": True,
            "approved": True,
            "status": "approved",
            "iv_context": {"iv_context": "cheap", "iv_rank": 18, "iv_percentile": 22},
            "greeks": {"greeks_quality": "good", "risk_level": "low"},
            "spread_quality": "good",
            "fill_quality": "good",
            "days_to_expiration": 25,
            "risk_multiplier": 1.0,
            "reasons": [],
            "warnings": [],
            "errors": [],
        },
        "options_research_status": "paper_eligible",
    }
    candidate.update(overrides)
    return candidate


def _recommendable_constraints() -> dict:
    return {
        "passed": True,
        "recommendation_status": "recommendable",
        "score": 91.5,
        "constraint_results": {},
        "failed_constraints": [],
        "rejection_reason": "",
        "config": {"minimum_risk_reward": 2.0},
    }


def test_build_trade_decision_rejects_blocking_filing_sentiment(tmp_path):
    candidate = _candidate("AAPL")
    candidate["filing_sentiment"] = {
        "ok": True,
        "sentiment_label": "negative",
        "filing_risk_level": "critical",
        "trade_impact": "blocking",
        "risk_multiplier": 0.0,
        "score_adjustment": -30.0,
        "reasons": ["Critical SEC filing risk blocks new paper recommendations."],
        "warnings": [],
    }

    decision = build_trade_decision(candidate, db_path=str(tmp_path / "brain.db"), include_memory_context=False)

    assert decision["decision"] == "reject"
    assert decision["data_used"]["sec_filings"] is True
    assert decision["filing_sentiment"]["trade_impact"] == "blocking"
    assert any("Critical SEC filing risk" in risk for risk in decision["risks"])


def test_build_trade_decision_rejects_critical_news_risk(tmp_path):
    candidate = _candidate("AAPL")
    candidate["news_sentiment"] = {
        "ok": True,
        "sentiment_label": "negative",
        "headline_risk_level": "critical",
        "trade_impact": "blocking",
        "risk_multiplier": 0.0,
        "score_adjustment": -30.0,
        "risk_flags": ["restatement"],
        "positive_flags": [],
        "warnings": [],
    }

    decision = build_trade_decision(candidate, db_path=str(tmp_path / "brain.db"), include_memory_context=False)

    assert decision["decision"] == "reject"
    assert decision["data_used"]["news_sentiment"] is True
    assert "restatement" in decision["risks"]


def test_build_trade_decision_attaches_human_feedback_without_unblocking_rejected_candidate(tmp_path):
    db_path = str(tmp_path / "memory_feedback.db")
    add_human_annotation(
        db_path=db_path,
        entity_type="trade",
        annotation_type="blocking",
        ticker="AAPL",
        setup_type="momentum_breakout",
        label="blocking",
        notes="Avoid this setup for now.",
    )
    candidate = _candidate("AAPL", recommendation_status="rejected", passed=False, risk_reward=1.2)

    decision = build_trade_decision(candidate, db_path=db_path, include_memory_context=True)

    assert decision["decision"] == "reject"
    assert decision["human_feedback"]["feedback_status"] == "blocking"
    assert decision["memory_context"]["memory_impact"]["trade_impact"] in {"blocking", "ignored"}
    assert any("blocking" in risk.lower() for risk in decision["risks"])


def test_build_trade_decision_combines_short_and_news_multipliers(tmp_path):
    candidate = _candidate("AAPL")
    candidate["short_interest"] = {
        "ok": True,
        "short_interest_level": "extreme",
        "squeeze_risk": "high",
        "trade_impact": "supportive",
        "risk_multiplier": 0.85,
        "score_adjustment": 4.0,
        "reasons": ["Extreme short interest may support a squeeze setup."],
        "warnings": [],
    }
    candidate["news_sentiment"] = {
        "ok": True,
        "sentiment_label": "negative",
        "headline_risk_level": "high",
        "trade_impact": "caution",
        "risk_multiplier": 0.5,
        "score_adjustment": -10.0,
        "risk_flags": ["investigation"],
        "positive_flags": [],
        "warnings": [],
    }

    decision = build_trade_decision(candidate, db_path=str(tmp_path / "brain.db"), include_memory_context=False)
    sizing = decision["position_sizing"]

    assert sizing["risk_multipliers"]["short_interest"] == 0.85
    assert sizing["risk_multipliers"]["news_sentiment"] == 0.5
    assert sizing["shares"] < sizing["original_position_sizing"]["shares"]


def test_weekly_trade_hunt_returns_structured_decision_object_and_does_not_log_when_disabled(monkeypatch, tmp_path):
    db_path = str(tmp_path / "brain_weekly.db")
    init_trade_tracking_db(db_path)

    monkeypatch.setattr(
        "agent.trading_brain.get_default_universe",
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
    monkeypatch.setattr(
        "agent.trading_brain.scan_multi_strategy_candidates",
        lambda **kwargs: {
            "ok": True,
            "profiles_run": ["momentum_breakout"],
            "best_candidates": [_candidate("AAPL")],
            "watchlist_candidates": [_candidate("MSFT", recommendation_status="watchlist", score=74.0)],
            "rejected_candidates": [_candidate("TSLA", recommendation_status="rejected", passed=False, score=40.0)],
        },
    )
    monkeypatch.setattr("agent.trading_brain.get_open_recommendations", lambda db_path="strategy_library.db": [])
    monkeypatch.setattr("agent.trading_brain.select_weekly_trades", lambda **kwargs: _selection_result(_candidate("AAPL")))
    monkeypatch.setattr("agent.trading_brain.get_win_loss_record", lambda db_path="strategy_library.db": {"wins": 0, "losses": 0, "win_rate": 0.0})
    monkeypatch.setattr("agent.trading_brain.get_strategy_performance", lambda db_path="strategy_library.db": {"overall": {"total_recommendations": 0}, "by_strategy": [], "by_setup_type": []})

    result = run_weekly_trade_hunt(auto_log=False, db_path=db_path)

    assert result["ok"] is True
    assert result["mode"] == "weekly_trade_hunt"
    assert result["decision_result"]["final_recommendations"]
    assert "position_sizing" in result["decision_result"]["final_recommendations"][0]
    assert "similar_setup_context" in result["decision_result"]["final_recommendations"][0]
    assert result["summary"]["logged_count"] == 0

    with sqlite3.connect(db_path) as conn:
        recommendation_count = conn.execute("SELECT COUNT(*) FROM trade_recommendations").fetchone()[0]
    assert recommendation_count == 0


def test_weekly_trade_hunt_blocks_candidate_when_data_quality_disallows_final_recommendation(monkeypatch, tmp_path):
    db_path = str(tmp_path / "brain_data_quality.db")
    init_trade_tracking_db(db_path)
    blocked_candidate = _candidate("AAPL")
    blocked_candidate["data_quality"] = {
        "quality_label": "poor",
        "final_recommendation_allowed": False,
        "warnings": ["IBKR live quote unavailable; using latest historical close."],
        "errors": ["Latest historical bar is stale."],
    }

    monkeypatch.setattr(
        "agent.trading_brain.get_default_universe",
        lambda universe="large_cap", max_tickers=500: {
            "ok": True,
            "tickers": ["AAPL"],
            "count": 1,
            "errors": [],
        },
    )
    monkeypatch.setattr(
        "agent.trading_brain.scan_multi_strategy_candidates",
        lambda **kwargs: {"ok": True, "profiles_run": ["momentum_breakout"], "best_candidates": [blocked_candidate], "watchlist_candidates": [], "rejected_candidates": []},
    )
    monkeypatch.setattr("agent.trading_brain.get_open_recommendations", lambda db_path="strategy_library.db": [])
    monkeypatch.setattr("agent.trading_brain.select_weekly_trades", lambda **kwargs: _selection_result(blocked_candidate))
    monkeypatch.setattr("agent.trading_brain.get_win_loss_record", lambda db_path="strategy_library.db": {"wins": 0, "losses": 0, "win_rate": 0.0})
    monkeypatch.setattr("agent.trading_brain.get_strategy_performance", lambda db_path="strategy_library.db": {"overall": {"total_recommendations": 0}, "by_strategy": [], "by_setup_type": []})

    result = run_weekly_trade_hunt(auto_log=True, include_market_regime=False, include_portfolio_risk=False, db_path=db_path)

    assert result["ok"] is True
    assert result["summary"]["selected_count"] == 0
    assert result["summary"]["logged_count"] == 0
    assert "stale" in result["decision_result"]["not_selected"][0]["reason"].lower()


def test_weekly_trade_hunt_includes_async_scan_execution_summary(monkeypatch, tmp_path):
    db_path = str(tmp_path / "brain_async_summary.db")
    init_trade_tracking_db(db_path)
    scan_summary = {
        "total_tickers": 2,
        "completed_tickers": 1,
        "failed_tickers": ["BAD"],
        "timed_out_tickers": [],
        "partial_results_used": True,
        "duration_seconds": 1.25,
        "warnings": ["Scan completed with partial results due to timeout or provider failures."],
    }

    monkeypatch.setattr(
        "agent.trading_brain.get_default_universe",
        lambda universe="large_cap", max_tickers=500: {"ok": True, "tickers": ["AAPL", "BAD"], "count": 2, "errors": []},
    )
    monkeypatch.setattr(
        "agent.trading_brain.scan_multi_strategy_candidates",
        lambda **kwargs: {
            "ok": True,
            "profiles_run": ["momentum_breakout"],
            "best_candidates": [_candidate("AAPL")],
            "watchlist_candidates": [],
            "rejected_candidates": [_candidate("BAD", recommendation_status="rejected", passed=False)],
            "scan_execution_summary": scan_summary,
            "errors": [],
        },
    )
    monkeypatch.setattr("agent.trading_brain.get_open_recommendations", lambda db_path="strategy_library.db": [])
    monkeypatch.setattr("agent.trading_brain.select_weekly_trades", lambda **kwargs: _selection_result(_candidate("AAPL")))
    monkeypatch.setattr("agent.trading_brain.get_win_loss_record", lambda db_path="strategy_library.db": {"wins": 0, "losses": 0, "win_rate": 0.0})
    monkeypatch.setattr("agent.trading_brain.get_strategy_performance", lambda db_path="strategy_library.db": {"overall": {"total_recommendations": 0}, "by_strategy": [], "by_setup_type": []})

    result = run_weekly_trade_hunt(auto_log=False, db_path=db_path)

    assert result["scan_execution_summary"] == scan_summary
    assert result["summary"]["scan_execution_summary"]["partial_results_used"] is True
    assert "partial results" in " ".join(result["errors"]).lower()


def test_blocked_circuit_breaker_prevents_paper_logging(monkeypatch, tmp_path):
    db_path = str(tmp_path / "brain_circuit_blocked.db")
    init_trade_tracking_db(db_path)

    monkeypatch.setattr("agent.trading_brain._load_paper_trade_history", lambda db_path: [{"outcome": "loss"}] * 7)
    monkeypatch.setattr(
        "agent.trading_brain.get_default_universe",
        lambda universe="large_cap", max_tickers=500: {"ok": True, "tickers": ["AAPL"], "count": 1, "errors": []},
    )
    monkeypatch.setattr(
        "agent.trading_brain.scan_multi_strategy_candidates",
        lambda **kwargs: {"ok": True, "profiles_run": ["momentum_breakout"], "best_candidates": [_candidate("AAPL")], "watchlist_candidates": [], "rejected_candidates": []},
    )
    monkeypatch.setattr("agent.trading_brain.get_open_recommendations", lambda db_path="strategy_library.db": [])
    monkeypatch.setattr("agent.trading_brain.get_win_loss_record", lambda db_path="strategy_library.db": {"wins": 0, "losses": 7, "win_rate": 0.0})
    monkeypatch.setattr("agent.trading_brain.get_strategy_performance", lambda db_path="strategy_library.db": {"overall": {"total_recommendations": 7}, "by_strategy": [], "by_setup_type": []})

    result = run_weekly_trade_hunt(
        auto_log=True,
        db_path=db_path,
        logging_metadata={"paper_trading": True, "execution_mode": "paper_trading"},
    )

    assert result["ok"] is True
    assert result["summary"]["selected_count"] == 0
    assert result["summary"]["logged_count"] == 0
    assert result["summary"]["circuit_breaker"]["circuit_status"] == "blocked"


def test_reduced_risk_circuit_multiplier_adjusts_position_sizing(monkeypatch, tmp_path):
    db_path = str(tmp_path / "brain_circuit_reduced.db")
    init_trade_tracking_db(db_path)
    candidate = _candidate("AAPL")

    monkeypatch.setattr("agent.trading_brain._load_paper_trade_history", lambda db_path: [{"outcome": "win"}, *[{"outcome": "loss"} for _ in range(5)]])
    monkeypatch.setattr(
        "agent.trading_brain.get_default_universe",
        lambda universe="large_cap", max_tickers=500: {"ok": True, "tickers": ["AAPL"], "count": 1, "errors": []},
    )
    monkeypatch.setattr(
        "agent.trading_brain.scan_multi_strategy_candidates",
        lambda **kwargs: {"ok": True, "profiles_run": ["momentum_breakout"], "best_candidates": [candidate], "watchlist_candidates": [], "rejected_candidates": []},
    )
    monkeypatch.setattr("agent.trading_brain.get_open_recommendations", lambda db_path="strategy_library.db": [])
    monkeypatch.setattr("agent.trading_brain.select_weekly_trades", lambda **kwargs: _selection_result(candidate))
    monkeypatch.setattr("agent.trading_brain.get_win_loss_record", lambda db_path="strategy_library.db": {"wins": 1, "losses": 5, "win_rate": 16.67})
    monkeypatch.setattr("agent.trading_brain.get_strategy_performance", lambda db_path="strategy_library.db": {"overall": {"total_recommendations": 6}, "by_strategy": [], "by_setup_type": []})
    monkeypatch.setattr("agent.trading_brain.evaluate_macro_risk", lambda: {"ok": True, "macro_risk_level": "low", "risk_multiplier": 1.0, "new_trades_allowed": True, "warnings": [], "reasons": []})

    result = run_weekly_trade_hunt(
        auto_log=False,
        include_market_regime=False,
        include_relative_strength=False,
        include_portfolio_risk=False,
        db_path=db_path,
        logging_metadata={"paper_trading": True, "execution_mode": "paper_trading"},
    )

    sizing = result["decision_result"]["final_recommendations"][0]["position_sizing"]
    assert result["summary"]["circuit_breaker"]["circuit_status"] == "reduced_risk"
    assert sizing["original_position_sizing"]["shares"] == 20
    assert sizing["shares"] == 10


def test_critical_macro_risk_blocks_final_recommendations(monkeypatch, tmp_path):
    db_path = str(tmp_path / "brain_macro_block.db")
    init_trade_tracking_db(db_path)
    candidate = _candidate("AAPL")

    monkeypatch.setattr("agent.trading_brain.get_default_universe", lambda **kwargs: {"ok": True, "tickers": ["AAPL"], "count": 1, "errors": []})
    monkeypatch.setattr("agent.trading_brain.scan_multi_strategy_candidates", lambda **kwargs: {"ok": True, "profiles_run": ["momentum_breakout"], "best_candidates": [candidate], "watchlist_candidates": [], "rejected_candidates": []})
    monkeypatch.setattr("agent.trading_brain.get_open_recommendations", lambda **kwargs: [])
    monkeypatch.setattr("agent.trading_brain.select_weekly_trades", lambda **kwargs: _selection_result(candidate))
    monkeypatch.setattr("agent.trading_brain.get_win_loss_record", lambda **kwargs: {"wins": 0, "losses": 0, "win_rate": 0.0})
    monkeypatch.setattr("agent.trading_brain.get_strategy_performance", lambda **kwargs: {"overall": {}})
    monkeypatch.setattr(
        "agent.trading_brain.evaluate_macro_risk",
        lambda: {
            "ok": True,
            "macro_risk_level": "critical",
            "risk_multiplier": 0.25,
            "new_trades_allowed": False,
            "event_window_active": True,
            "active_events": [{"event_type": "FOMC"}],
            "upcoming_events": [],
            "warnings": ["Critical macro event window blocks new trades."],
            "reasons": ["1 macro risk window(s) active."],
        },
    )

    result = run_weekly_trade_hunt(auto_log=True, include_market_regime=False, include_portfolio_risk=False, db_path=db_path)

    assert result["ok"] is True
    assert result["macro_risk"]["macro_risk_level"] == "critical"
    assert result["summary"]["selected_count"] == 0
    assert result["summary"]["logged_count"] == 0
    assert result["decision_result"]["final_recommendations"] == []

    with sqlite3.connect(db_path) as conn:
        count = conn.execute("SELECT COUNT(*) FROM trade_recommendations").fetchone()[0]
    assert count == 0


def test_build_trade_decision_combines_circuit_macro_and_regime_multipliers(tmp_path):
    candidate = _candidate("AAPL")
    candidate["circuit_breaker_context"] = {"circuit_status": "reduced_risk", "max_allowed_risk_multiplier": 0.5}
    candidate["macro_risk_context"] = {"macro_risk_level": "high", "risk_multiplier": 0.5, "new_trades_allowed": True}
    candidate["market_regime_context"] = {"regime": "weak_bull_chop", "stock_risk_multiplier": 0.75, "option_risk_multiplier": 0.5}
    candidate["concentration_risk_context"] = {"risk_level": "high", "risk_multiplier": 0.5, "reasons": ["High correlation."]}

    decision = build_trade_decision(candidate, db_path=str(tmp_path / "brain_multiplier.db"), include_memory_context=False)
    sizing = decision["position_sizing"]

    assert sizing["original_position_sizing"]["shares"] == 20
    assert sizing["shares"] == 1
    assert sizing["combined_risk_multiplier"] == 0.09375
    assert sizing["risk_multipliers"]["circuit_breaker"] == 0.5
    assert sizing["risk_multipliers"]["macro_risk"] == 0.5
    assert sizing["risk_multipliers"]["market_regime"] == 0.75
    assert sizing["risk_multipliers"]["concentration"] == 0.5


def test_concentration_controls_block_candidate_before_logging(monkeypatch, tmp_path):
    db_path = str(tmp_path / "brain_concentration_block.db")
    init_trade_tracking_db(db_path)
    candidate = _candidate("AAPL")

    monkeypatch.setattr("agent.trading_brain.get_default_universe", lambda **kwargs: {"ok": True, "tickers": ["AAPL"], "count": 1, "errors": []})
    monkeypatch.setattr("agent.trading_brain.scan_multi_strategy_candidates", lambda **kwargs: {"ok": True, "profiles_run": ["momentum_breakout"], "best_candidates": [candidate], "watchlist_candidates": [], "rejected_candidates": []})
    monkeypatch.setattr(
        "agent.trading_brain.get_open_recommendations",
        lambda **kwargs: [
            {
                "ticker": "AAPL",
                "asset_type": "stock",
                "direction": "long",
                "sector": "tech",
                "entry_price": 100.0,
                "stop_loss": 90.0,
                "target_price": 120.0,
                "quantity": 150,
                "status": "open",
            }
        ],
    )
    monkeypatch.setattr("agent.trading_brain.select_weekly_trades", lambda **kwargs: _selection_result(candidate))
    monkeypatch.setattr("agent.trading_brain.get_win_loss_record", lambda **kwargs: {"wins": 0, "losses": 0, "win_rate": 0.0})
    monkeypatch.setattr("agent.trading_brain.get_strategy_performance", lambda **kwargs: {"overall": {}})
    monkeypatch.setattr("agent.trading_brain.evaluate_macro_risk", lambda: {"ok": True, "macro_risk_level": "low", "risk_multiplier": 1.0, "new_trades_allowed": True, "warnings": [], "reasons": []})
    monkeypatch.setattr(
        "agent.trading_brain._load_or_refresh_correlation_context",
        lambda **kwargs: (
            {"correlations": {"AAPL": {"AAPL": 1.0}}, "tickers": ["AAPL"]},
            {"ok": True, "source": "latest_snapshot", "warnings": [], "errors": []},
        ),
    )

    result = run_weekly_trade_hunt(auto_log=True, include_portfolio_risk=False, db_path=db_path)

    assert result["ok"] is True
    assert result["summary"]["selected_count"] == 0
    assert result["summary"]["logged_count"] == 0
    assert result["selection_result"]["rejected_candidates"][0]["failed_constraints"][-1] == "concentration_risk_blocked"
    assert result["concentration_summary"]["blocked_count"] == 1

    with sqlite3.connect(db_path) as conn:
        count = conn.execute("SELECT COUNT(*) FROM trade_recommendations").fetchone()[0]
    assert count == 0


def test_build_trade_decision_applies_technical_confirmation_multiplier(tmp_path):
    candidate = _candidate("AAPL")
    candidate["technical_confirmation_summary"] = {
        "status": "warning",
        "score_adjustment": -5.0,
        "risk_multiplier": 0.5,
        "reasons": ["Weekly trend is neutral."],
        "warnings": [],
    }

    decision = build_trade_decision(candidate, db_path=str(tmp_path / "technical_multiplier.db"), include_memory_context=False)
    sizing = decision["position_sizing"]

    assert sizing["original_position_sizing"]["shares"] == 20
    assert sizing["shares"] == 10
    assert sizing["risk_multipliers"]["technical_confirmation"] == 0.5


def test_technical_rejected_candidate_is_not_logged(monkeypatch, tmp_path):
    db_path = str(tmp_path / "brain_technical_rejected.db")
    init_trade_tracking_db(db_path)
    candidate = _candidate("AAPL")
    candidate["technical_confirmation_summary"] = {
        "status": "rejected",
        "score_adjustment": -25.0,
        "risk_multiplier": 0.0,
        "reasons": ["Daily and weekly trends conflict."],
        "warnings": [],
    }

    monkeypatch.setattr("agent.trading_brain.get_default_universe", lambda **kwargs: {"ok": True, "tickers": ["AAPL"], "count": 1, "errors": []})
    monkeypatch.setattr("agent.trading_brain.scan_multi_strategy_candidates", lambda **kwargs: {"ok": True, "profiles_run": ["momentum_breakout"], "best_candidates": [candidate], "watchlist_candidates": [], "rejected_candidates": []})
    monkeypatch.setattr("agent.trading_brain.get_open_recommendations", lambda **kwargs: [])
    monkeypatch.setattr("agent.trading_brain.select_weekly_trades", lambda **kwargs: _selection_result(candidate))
    monkeypatch.setattr("agent.trading_brain.get_win_loss_record", lambda **kwargs: {"wins": 0, "losses": 0, "win_rate": 0.0})
    monkeypatch.setattr("agent.trading_brain.get_strategy_performance", lambda **kwargs: {"overall": {}})
    monkeypatch.setattr("agent.trading_brain.evaluate_macro_risk", lambda: {"ok": True, "macro_risk_level": "low", "risk_multiplier": 1.0, "new_trades_allowed": True, "warnings": [], "reasons": []})
    monkeypatch.setattr("agent.trading_brain._load_or_refresh_correlation_context", lambda **kwargs: (None, {"ok": False, "source": "unavailable", "warnings": [], "errors": []}))

    result = run_weekly_trade_hunt(auto_log=True, include_market_regime=False, include_portfolio_risk=False, db_path=db_path)

    assert result["summary"]["logged_count"] == 0
    assert result["decision_result"]["not_selected"][0]["reason"] == "Technical confirmation rejected candidate."
    with sqlite3.connect(db_path) as conn:
        assert conn.execute("SELECT COUNT(*) FROM trade_recommendations").fetchone()[0] == 0


def test_disabled_setup_decay_rejects_candidate(monkeypatch, tmp_path):
    db_path = str(tmp_path / "brain_setup_disabled.db")
    init_trade_tracking_db(db_path)
    candidate = _candidate("AAPL")
    disabled_decay = {
        "ok": True,
        "setups": {
            "momentum_breakout": {
                "ok": True,
                "setup_name": "momentum_breakout",
                "status": "disabled",
                "sample_size": 15,
                "recent_win_rate": 0.0,
                "recent_expectancy_r": -1.0,
                "avg_hold_days": 7,
                "reasons": ["Setup disabled by test."],
                "warnings": [],
            }
        },
        "counts": {"disabled": 1},
        "warnings": [],
    }

    monkeypatch.setattr("agent.trading_brain._load_paper_trade_history", lambda db_path: [])
    monkeypatch.setattr("agent.trading_brain.evaluate_drawdown_circuit_breaker", lambda *args, **kwargs: {"ok": True, "circuit_status": "normal", "new_trades_allowed": True, "max_allowed_risk_multiplier": 1.0, "warnings": [], "reasons": [], "rolling_loss_streak": 0, "recent_win_rate": None, "recent_expectancy_r": None, "realized_drawdown_percent": 0})
    monkeypatch.setattr("agent.trading_brain.evaluate_all_setup_decay", lambda *args, **kwargs: disabled_decay)
    monkeypatch.setattr(
        "agent.trading_brain.get_default_universe",
        lambda universe="large_cap", max_tickers=500: {"ok": True, "tickers": ["AAPL"], "count": 1, "errors": []},
    )
    monkeypatch.setattr(
        "agent.trading_brain.scan_multi_strategy_candidates",
        lambda **kwargs: {"ok": True, "profiles_run": ["momentum_breakout"], "best_candidates": [candidate], "watchlist_candidates": [], "rejected_candidates": []},
    )
    monkeypatch.setattr("agent.trading_brain.get_open_recommendations", lambda db_path="strategy_library.db": [])
    monkeypatch.setattr("agent.trading_brain.select_weekly_trades", lambda **kwargs: _selection_result(candidate))
    monkeypatch.setattr("agent.trading_brain.get_win_loss_record", lambda db_path="strategy_library.db": {"wins": 0, "losses": 0, "win_rate": 0.0})
    monkeypatch.setattr("agent.trading_brain.get_strategy_performance", lambda db_path="strategy_library.db": {"overall": {"total_recommendations": 0}, "by_strategy": [], "by_setup_type": []})

    result = run_weekly_trade_hunt(
        auto_log=True,
        include_market_regime=False,
        include_relative_strength=False,
        include_portfolio_risk=False,
        db_path=db_path,
        logging_metadata={"paper_trading": True, "execution_mode": "paper_trading"},
    )

    assert result["summary"]["selected_count"] == 0
    assert result["summary"]["logged_count"] == 0
    assert result["selection_result"]["rejected_candidates"][0]["failed_constraints"][-1] == "setup_decay_disabled"


def test_weekly_trade_hunt_auto_log_logs_only_valid_final_recommendations(monkeypatch, tmp_path):
    db_path = str(tmp_path / "brain_auto_log.db")
    init_trade_tracking_db(db_path)

    monkeypatch.setattr(
        "agent.trading_brain.get_default_universe",
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
    monkeypatch.setattr(
        "agent.trading_brain.scan_multi_strategy_candidates",
        lambda **kwargs: {"ok": True, "profiles_run": ["momentum_breakout"], "best_candidates": [], "watchlist_candidates": [], "rejected_candidates": []},
    )
    monkeypatch.setattr("agent.trading_brain.get_open_recommendations", lambda db_path="strategy_library.db": [])
    monkeypatch.setattr(
        "agent.trading_brain.select_weekly_trades",
        lambda **kwargs: _selection_result(
            _candidate("AAPL"),
            _candidate("MSFT", recommendation_status="watchlist", score=75.0),
            _candidate("TSLA", recommendation_status="rejected", passed=False, score=42.0),
        ),
    )
    monkeypatch.setattr("agent.trading_brain.get_win_loss_record", lambda db_path="strategy_library.db": {"wins": 0, "losses": 0, "win_rate": 0.0})
    monkeypatch.setattr("agent.trading_brain.get_strategy_performance", lambda db_path="strategy_library.db": {"overall": {"total_recommendations": 0}, "by_strategy": [], "by_setup_type": []})

    result = run_weekly_trade_hunt(auto_log=True, db_path=db_path)

    assert result["ok"] is True
    assert len(result["decision_result"]["final_recommendations"]) == 1
    assert len(result["decision_result"]["logged_recommendations"]) == 1
    assert result["decision_result"]["final_recommendations"][0]["ticker"] == "AAPL"

    with sqlite3.connect(db_path) as conn:
        rows = conn.execute("SELECT ticker FROM trade_recommendations ORDER BY id ASC").fetchall()
    assert [row[0] for row in rows] == ["AAPL"]


def test_paper_auto_log_stores_fill_context(monkeypatch, tmp_path):
    db_path = str(tmp_path / "brain_paper_fill.db")
    init_trade_tracking_db(db_path)
    candidate = _candidate("AAPL", target_price=125.0, risk_reward=5.0)
    candidate["average_volume_20"] = 50_000_000

    monkeypatch.setattr(
        "agent.trading_brain.get_default_universe",
        lambda universe="large_cap", max_tickers=500: {"ok": True, "tickers": ["AAPL"], "count": 1, "errors": []},
    )
    monkeypatch.setattr(
        "agent.trading_brain.scan_multi_strategy_candidates",
        lambda **kwargs: {"ok": True, "profiles_run": ["momentum_breakout"], "best_candidates": [candidate], "watchlist_candidates": [], "rejected_candidates": []},
    )
    monkeypatch.setattr("agent.trading_brain.get_open_recommendations", lambda db_path="strategy_library.db": [])
    monkeypatch.setattr("agent.trading_brain.select_weekly_trades", lambda **kwargs: _selection_result(candidate))
    monkeypatch.setattr("agent.trading_brain.get_win_loss_record", lambda db_path="strategy_library.db": {"wins": 0, "losses": 0, "win_rate": 0.0})
    monkeypatch.setattr("agent.trading_brain.get_strategy_performance", lambda db_path="strategy_library.db": {"overall": {"total_recommendations": 0}, "by_strategy": [], "by_setup_type": []})

    result = run_weekly_trade_hunt(
        auto_log=True,
        include_portfolio_risk=False,
        db_path=db_path,
        logging_metadata={"paper_trading": True, "execution_mode": "paper_trading"},
    )

    assert result["summary"]["logged_count"] == 1
    with sqlite3.connect(db_path) as conn:
        row = conn.execute("SELECT entry_price, data_snapshot_json FROM trade_recommendations").fetchone()
    payload = json.loads(row[1])
    assert payload["intended_entry_price"] == 100.0
    assert payload["paper_fill"]["ok"] is True
    assert row[0] == payload["paper_fill"]["estimated_fill_price"]


def test_paper_option_without_fill_is_not_logged(monkeypatch, tmp_path):
    db_path = str(tmp_path / "brain_option_fill_block.db")
    init_trade_tracking_db(db_path)
    candidate = _candidate("AAPL", target_price=125.0, risk_reward=5.0)
    candidate["option_alternatives"] = [
        _option_candidate(bid=None, ask=None, spread_percent=0.05, mid=3.9)
    ]

    monkeypatch.setattr(
        "agent.trading_brain.get_default_universe",
        lambda universe="large_cap", max_tickers=500: {"ok": True, "tickers": ["AAPL"], "count": 1, "errors": []},
    )
    monkeypatch.setattr(
        "agent.trading_brain.scan_multi_strategy_candidates",
        lambda **kwargs: {"ok": True, "profiles_run": ["momentum_breakout"], "best_candidates": [candidate], "watchlist_candidates": [], "rejected_candidates": []},
    )
    monkeypatch.setattr("agent.trading_brain.get_open_recommendations", lambda db_path="strategy_library.db": [])
    monkeypatch.setattr("agent.trading_brain.select_weekly_trades", lambda **kwargs: _selection_result(candidate))
    monkeypatch.setattr("agent.trading_brain.get_win_loss_record", lambda db_path="strategy_library.db": {"wins": 0, "losses": 0, "win_rate": 0.0})
    monkeypatch.setattr("agent.trading_brain.get_strategy_performance", lambda db_path="strategy_library.db": {"overall": {"total_recommendations": 0}, "by_strategy": [], "by_setup_type": []})

    result = run_weekly_trade_hunt(
        auto_log=True,
        prefer_options=True,
        include_market_regime=False,
        include_relative_strength=False,
        include_portfolio_risk=False,
        include_position_sizing=False,
        db_path=db_path,
        logging_metadata={"paper_trading": True, "execution_mode": "paper_trading"},
    )

    assert result["summary"]["logged_count"] == 0
    assert result["errors"]
    with sqlite3.connect(db_path) as conn:
        count = conn.execute("SELECT COUNT(*) FROM trade_recommendations").fetchone()[0]
    assert count == 0


def test_weekly_trade_hunt_applies_portfolio_risk_before_final_recommendations(monkeypatch, tmp_path):
    db_path = str(tmp_path / "brain_portfolio_risk.db")
    init_trade_tracking_db(db_path)

    monkeypatch.setattr(
        "agent.trading_brain.get_default_universe",
        lambda universe="large_cap", max_tickers=500: {
            "ok": True,
            "universe": universe,
            "timestamp": "2026-06-05T00:00:00+00:00",
            "tickers": ["AAPL", "MSFT"],
            "count": 2,
            "source": "static_curated",
            "max_tickers": max_tickers,
            "errors": [],
        },
    )
    monkeypatch.setattr(
        "agent.trading_brain.scan_multi_strategy_candidates",
        lambda **kwargs: {"ok": True, "profiles_run": ["momentum_breakout"], "best_candidates": [], "watchlist_candidates": [], "rejected_candidates": []},
    )
    monkeypatch.setattr("agent.trading_brain.get_open_recommendations", lambda db_path="strategy_library.db": [])
    monkeypatch.setattr(
        "agent.trading_brain.select_weekly_trades",
        lambda **kwargs: _selection_result(_candidate("AAPL", score=95.0), _candidate("MSFT", score=90.0)),
    )
    monkeypatch.setattr(
        "agent.trading_brain.apply_portfolio_risk_limits",
        lambda proposed_trades, existing_open_trades=None, account_size=10000.0, config=None: {
            "ok": True,
            "approved_trades": [proposed_trades[0]],
            "rejected_trades": [
                {
                    "ticker": "MSFT",
                    "trade": proposed_trades[1],
                    "rejection_reason": "Trade would exceed max_same_sector_trades.",
                }
            ],
            "risk_summary": {"message": "Portfolio risk check completed."},
        },
    )
    monkeypatch.setattr("agent.trading_brain.get_win_loss_record", lambda db_path="strategy_library.db": {"wins": 0, "losses": 0, "win_rate": 0.0})
    monkeypatch.setattr("agent.trading_brain.get_strategy_performance", lambda db_path="strategy_library.db": {"overall": {"total_recommendations": 0}, "by_strategy": [], "by_setup_type": []})

    result = run_weekly_trade_hunt(
        include_portfolio_risk=True,
        account_size=25000.0,
        risk_mode="conservative",
        auto_log=False,
        db_path=db_path,
    )

    assert result["ok"] is True
    assert result["portfolio_risk"]["approved_trades"][0]["ticker"] == "AAPL"
    assert result["decision_result"]["final_recommendations"][0]["ticker"] == "AAPL"
    assert result["decision_result"]["risk_rejected"][0]["ticker"] == "MSFT"


def test_weekly_trade_hunt_preserves_behavior_when_position_sizing_disabled(monkeypatch, tmp_path):
    db_path = str(tmp_path / "brain_no_position_sizing.db")
    init_trade_tracking_db(db_path)

    monkeypatch.setattr("agent.trading_brain.get_default_universe", lambda **kwargs: {"ok": True, "tickers": ["AAPL"], "count": 1, "errors": []})
    monkeypatch.setattr("agent.trading_brain.scan_multi_strategy_candidates", lambda **kwargs: {"ok": True, "profiles_run": ["momentum_breakout"]})
    monkeypatch.setattr("agent.trading_brain.get_open_recommendations", lambda **kwargs: [])
    monkeypatch.setattr("agent.trading_brain.select_weekly_trades", lambda **kwargs: _selection_result(_candidate("AAPL")))
    monkeypatch.setattr("agent.trading_brain.get_win_loss_record", lambda **kwargs: {"wins": 0, "losses": 0, "win_rate": 0.0})
    monkeypatch.setattr("agent.trading_brain.get_strategy_performance", lambda **kwargs: {"overall": {}})

    result = run_weekly_trade_hunt(include_position_sizing=False, db_path=db_path)

    assert result["ok"] is True
    assert result["decision_result"]["final_recommendations"]
    assert result["decision_result"]["final_recommendations"][0]["position_sizing"] is None


def test_weekly_trade_hunt_can_disable_memory_context(monkeypatch, tmp_path):
    db_path = str(tmp_path / "brain_no_memory_context.db")
    init_trade_tracking_db(db_path)

    monkeypatch.setattr("agent.trading_brain.get_default_universe", lambda **kwargs: {"ok": True, "tickers": ["AAPL"], "count": 1, "errors": []})
    monkeypatch.setattr("agent.trading_brain.scan_multi_strategy_candidates", lambda **kwargs: {"ok": True, "profiles_run": ["momentum_breakout"]})
    monkeypatch.setattr("agent.trading_brain.get_open_recommendations", lambda **kwargs: [])
    monkeypatch.setattr("agent.trading_brain.select_weekly_trades", lambda **kwargs: _selection_result(_candidate("AAPL")))
    monkeypatch.setattr("agent.trading_brain.get_win_loss_record", lambda **kwargs: {"wins": 0, "losses": 0, "win_rate": 0.0})
    monkeypatch.setattr("agent.trading_brain.get_strategy_performance", lambda **kwargs: {"overall": {}})

    result = run_weekly_trade_hunt(include_memory_context=False, db_path=db_path)

    assert result["ok"] is True
    assert result["decision_result"]["final_recommendations"][0]["similar_setup_context"] is None


def test_weekly_trade_hunt_store_memory_false_does_not_write(monkeypatch, tmp_path):
    db_path = str(tmp_path / "brain_memory_false.db")
    init_trade_tracking_db(db_path)
    writes = []

    monkeypatch.setattr("agent.trading_brain.get_default_universe", lambda **kwargs: {"ok": True, "tickers": ["AAPL"], "count": 1, "errors": []})
    monkeypatch.setattr("agent.trading_brain.scan_multi_strategy_candidates", lambda **kwargs: {"ok": True, "profiles_run": ["momentum_breakout"]})
    monkeypatch.setattr("agent.trading_brain.get_open_recommendations", lambda **kwargs: [])
    monkeypatch.setattr("agent.trading_brain.select_weekly_trades", lambda **kwargs: _selection_result(_candidate("AAPL")))
    monkeypatch.setattr("agent.trading_brain.get_win_loss_record", lambda **kwargs: {"wins": 0, "losses": 0, "win_rate": 0.0})
    monkeypatch.setattr("agent.trading_brain.get_strategy_performance", lambda **kwargs: {"overall": {}})
    monkeypatch.setattr("agent.trading_brain.store_trade_decision_memory", lambda *args, **kwargs: writes.append("trade") or {"ok": True})

    result = run_weekly_trade_hunt(store_memory=False, db_path=db_path)

    assert result["ok"] is True
    assert writes == []
    assert result["decision_result"]["memory_write_results"] == []


def test_weekly_trade_hunt_store_memory_attempts_writes_without_breaking(monkeypatch, tmp_path):
    db_path = str(tmp_path / "brain_memory_true.db")
    init_trade_tracking_db(db_path)

    monkeypatch.setattr("agent.trading_brain.get_default_universe", lambda **kwargs: {"ok": True, "tickers": ["AAPL"], "count": 1, "errors": []})
    monkeypatch.setattr("agent.trading_brain.scan_multi_strategy_candidates", lambda **kwargs: {"ok": True, "profiles_run": ["momentum_breakout"]})
    monkeypatch.setattr("agent.trading_brain.get_open_recommendations", lambda **kwargs: [])
    monkeypatch.setattr("agent.trading_brain.select_weekly_trades", lambda **kwargs: _selection_result(_candidate("AAPL")))
    monkeypatch.setattr("agent.trading_brain.get_win_loss_record", lambda **kwargs: {"wins": 0, "losses": 0, "win_rate": 0.0})
    monkeypatch.setattr("agent.trading_brain.get_strategy_performance", lambda **kwargs: {"overall": {}})
    monkeypatch.setattr(
        "agent.trading_brain.store_trade_decision_memory",
        lambda *args, **kwargs: {"ok": False, "source": "unavailable", "error": "No memory provider."},
    )

    result = run_weekly_trade_hunt(store_memory=True, db_path=db_path)

    assert result["ok"] is True
    assert result["decision_result"]["memory_write_results"][0]["ok"] is False
    assert result["decision_result"]["memory_write_results"][0]["error"] == "No memory provider."


def test_review_ticker_opportunity_returns_status_and_reasons(monkeypatch):
    snapshots = {
        "AAPL": {"ok": True, "ticker": "AAPL", "data": {"quote": {"last_price": 120.0}, "technical_snapshot": {"current_price": 120.0, "sma_20": 118.0, "sma_50": 116.0, "high_20": 121.0, "atr_14": 2.0}, "data_freshness": {"freshness_label": "fresh"}}},
        "MSFT": {"ok": True, "ticker": "MSFT", "data": {"quote": {"last_price": 100.0}, "technical_snapshot": {"current_price": 100.0, "sma_20": 99.0, "sma_50": 98.0, "high_20": 101.0, "atr_14": 1.0}, "data_freshness": {"freshness_label": "fresh"}}},
        "TSLA": {"ok": True, "ticker": "TSLA", "data": {"quote": {"last_price": 80.0}, "technical_snapshot": {"current_price": 80.0, "sma_20": 84.0, "sma_50": 86.0, "high_20": 88.0, "atr_14": 1.2}, "data_freshness": {"freshness_label": "fresh"}}},
    }
    statuses = {
        "AAPL": {"passed": True, "recommendation_status": "recommendable", "score": 91.0, "constraint_results": {}, "failed_constraints": [], "rejection_reason": "", "config": {"minimum_risk_reward": 2.0}},
        "MSFT": {"passed": True, "recommendation_status": "watchlist", "score": 74.0, "constraint_results": {}, "failed_constraints": [], "rejection_reason": "", "config": {"minimum_risk_reward": 2.0}},
        "TSLA": {"passed": False, "recommendation_status": "rejected", "score": 42.0, "constraint_results": {}, "failed_constraints": ["minimum_relative_volume"], "rejection_reason": "Failed liquidity.", "config": {"minimum_risk_reward": 2.0}},
    }

    monkeypatch.setattr("agent.trading_brain.get_market_snapshot", lambda ticker, lookback_days=180: snapshots[ticker])
    monkeypatch.setattr("agent.trading_brain.calculate_trade_levels", lambda technical_snapshot, direction="long": {"ok": True, "entry_price": technical_snapshot["current_price"], "target_price": technical_snapshot["current_price"] + 10, "stop_loss": technical_snapshot["current_price"] - 5, "risk_reward": 2.0, "error": None})
    monkeypatch.setattr("agent.trading_brain.evaluate_stock_constraints", lambda candidate: statuses[candidate["ticker"]])
    monkeypatch.setattr("agent.trading_brain.enrich_candidate_with_statistics", lambda candidate, db_path="strategy_library.db": {**candidate, "statistical_context": {"confidence_label": "medium", "warnings": [], "ticker_history": {"historical_edge": "neutral", "closed_trades": 2}, "setup_performance": None, "profile_performance": None, "statistical_score": 40.0}})
    monkeypatch.setattr("agent.trading_brain.enrich_candidate_with_catalysts", lambda candidate: {**candidate, "catalyst_context": {"catalyst_label": "neutral", "positive_catalysts": [], "negative_catalysts": [], "risk_flags": [], "catalyst_bias": 0.0}})

    aapl = review_ticker_opportunity("AAPL")
    msft = review_ticker_opportunity("MSFT")
    tsla = review_ticker_opportunity("TSLA")

    assert aapl["status"] == "recommendable"
    assert msft["status"] == "watchlist"
    assert tsla["status"] == "rejected"
    assert aapl["reasons"]
    assert tsla["failed_constraints"]


def test_review_ticker_opportunity_returns_ranking_unavailable_for_provider_failure(monkeypatch):
    provider_error = "IBKR client ID is already in use. Close stale TWS sessions or use a unique IBKR_CLIENT_ID."
    monkeypatch.setattr(
        "agent.trading_brain.get_market_snapshot",
        lambda ticker, lookback_days=180: {
            "ok": False,
            "ticker": ticker,
            "source": "unavailable",
            "error": provider_error,
            "error_type": "provider",
            "data": None,
        },
    )

    result = review_ticker_opportunity("AAPL")

    assert result["ok"] is True
    assert result["status"] == "ranking_unavailable"
    assert result["ticker"] == "AAPL"
    assert result["candidate"] is None
    assert result["decision"] is None
    assert provider_error in result["warnings"]
    assert provider_error in result["reasons"]
    assert result["market_snapshot"]["error_type"] == "provider"


def test_review_ticker_opportunity_attaches_research_brief(monkeypatch):
    snapshot = {
        "ok": True,
        "ticker": "AAPL",
        "data": {
            "quote": {"last_price": 120.0},
            "technical_snapshot": {
                "current_price": 120.0,
                "sma_20": 118.0,
                "sma_50": 116.0,
                "high_20": 121.0,
                "atr_14": 2.0,
            },
            "data_freshness": {"freshness_label": "fresh"},
        },
    }

    monkeypatch.setattr("agent.trading_brain.get_market_snapshot", lambda ticker, lookback_days=180: snapshot)
    monkeypatch.setattr("agent.trading_brain.calculate_trade_levels", lambda technical_snapshot, direction="long": {"ok": True, "entry_price": 120.0, "target_price": 130.0, "stop_loss": 115.0, "risk_reward": 2.0, "error": None})
    monkeypatch.setattr("agent.trading_brain.evaluate_stock_constraints", lambda candidate: {"passed": True, "recommendation_status": "recommendable", "score": 90.0, "constraint_results": {}, "failed_constraints": [], "rejection_reason": "", "config": {"minimum_risk_reward": 2.0}})
    monkeypatch.setattr("agent.trading_brain.enrich_candidate_with_statistics", lambda candidate, db_path="strategy_library.db": {**candidate, "statistical_context": {"confidence_label": "medium", "warnings": [], "ticker_history": {"historical_edge": "positive", "closed_trades": 5}, "setup_performance": {"expectancy": 0.06}, "profile_performance": None, "statistical_score": 68.0}})
    monkeypatch.setattr("agent.trading_brain.enrich_candidate_with_catalysts", lambda candidate: {**candidate, "catalyst_context": {"catalyst_label": "positive", "positive_catalysts": ["Upgrade"], "negative_catalysts": [], "risk_flags": [], "catalyst_bias": 3.0}})
    monkeypatch.setattr(
        "research.deep_research.build_research_brief",
        lambda **kwargs: {
            "ok": True,
            "ticker": kwargs["ticker"],
            "brief_type": "deep_research",
            "research_summary": "AAPL deep research summary.",
            "research_conviction": {"score": 74.0, "label": "medium"},
            "bull_case": {"points": ["Passed constraints."]},
            "bear_case": {"points": ["Normal pullback risk."]},
            "key_risks": ["Pullback risk"],
            "raw_context": {"relative_strength": {"ok": True, "relative_strength_label": "outperforming"}},
        },
    )

    result = review_ticker_opportunity("AAPL", include_research_brief=True)

    assert result["ok"] is True
    assert result["research_brief"]["brief_type"] == "deep_research"
    assert result["decision"]["research_summary"] == "AAPL deep research summary."
    assert result["reasons"][0] == "AAPL deep research summary."


def test_monitor_open_trades_returns_open_trades_and_performance_context(monkeypatch, tmp_path):
    db_path = str(tmp_path / "brain_monitor.db")
    init_trade_tracking_db(db_path)
    log_recommendation_tool(
        ticker="AAPL",
        asset_type="stock",
        direction="long",
        strategy="test_strategy",
        entry_price=100.0,
        target_price=110.0,
        stop_loss=95.0,
        risk_reward=2.0,
        constraint_results=_recommendable_constraints(),
        db_path=db_path,
    )

    monkeypatch.setattr(
        "agent.trading_brain.update_open_recommendations",
        lambda db_path="strategy_library.db": {"ok": True, "checked": 1, "updated": 0, "still_open": 1, "manual_review": 0, "errors": [], "results": []},
    )

    result = monitor_open_trades(db_path=db_path)

    assert result["ok"] is True
    assert result["mode"] == "monitor_open_trades"
    assert len(result["open_recommendations"]) == 1
    assert "win_loss_record" in result["performance_context"]


def test_weekly_trade_hunt_include_options_false_preserves_old_behavior(monkeypatch, tmp_path):
    db_path = str(tmp_path / "brain_no_options.db")
    init_trade_tracking_db(db_path)

    monkeypatch.setattr("agent.trading_brain.get_default_universe", lambda **kwargs: {"ok": True, "tickers": ["AAPL"], "count": 1, "errors": []})
    monkeypatch.setattr("agent.trading_brain.scan_multi_strategy_candidates", lambda **kwargs: {"ok": True, "profiles_run": ["momentum_breakout"]})
    monkeypatch.setattr("agent.trading_brain.get_open_recommendations", lambda db_path="strategy_library.db": [])
    monkeypatch.setattr("agent.trading_brain.select_weekly_trades", lambda **kwargs: _selection_result(_candidate("AAPL")))
    monkeypatch.setattr("agent.trading_brain.get_win_loss_record", lambda **kwargs: {"wins": 0, "losses": 0, "win_rate": 0.0})
    monkeypatch.setattr("agent.trading_brain.get_strategy_performance", lambda **kwargs: {"overall": {}})
    monkeypatch.setattr("agent.trading_brain.get_market_regime_snapshot", lambda **kwargs: {"ok": True, "regime": "risk_on_uptrend", "summary": "Risk on.", "options_aggressiveness": "normal", "max_trades_adjustment": 1, "trade_aggressiveness": "normal", "risk_flags": []})
    monkeypatch.setattr("agent.trading_brain.apply_regime_to_trade_selection", lambda selection_result, regime_result: selection_result)

    result = run_weekly_trade_hunt(include_options=False, db_path=db_path)

    assert result["ok"] is True
    assert result["option_research"] is None
    assert result["decision_result"]["final_recommendations"][0]["preferred_instrument"] == "stock"


def test_weekly_trade_hunt_can_attach_research_briefs_to_final_recommendations(monkeypatch, tmp_path):
    db_path = str(tmp_path / "brain_research.db")
    init_trade_tracking_db(db_path)

    monkeypatch.setattr("agent.trading_brain.get_default_universe", lambda **kwargs: {"ok": True, "tickers": ["AAPL"], "count": 1, "errors": []})
    monkeypatch.setattr("agent.trading_brain.scan_multi_strategy_candidates", lambda **kwargs: {"ok": True, "profiles_run": ["momentum_breakout"]})
    monkeypatch.setattr("agent.trading_brain.get_open_recommendations", lambda db_path="strategy_library.db": [])
    monkeypatch.setattr("agent.trading_brain.select_weekly_trades", lambda **kwargs: _selection_result(_candidate("AAPL")))
    monkeypatch.setattr("agent.trading_brain.get_win_loss_record", lambda **kwargs: {"wins": 0, "losses": 0, "win_rate": 0.0})
    monkeypatch.setattr("agent.trading_brain.get_strategy_performance", lambda **kwargs: {"overall": {}})
    monkeypatch.setattr("agent.trading_brain.get_market_regime_snapshot", lambda **kwargs: {"ok": True, "regime": "risk_on_uptrend", "summary": "Risk on.", "options_aggressiveness": "normal", "max_trades_adjustment": 1, "trade_aggressiveness": "normal", "risk_flags": []})
    monkeypatch.setattr("agent.trading_brain.apply_regime_to_trade_selection", lambda selection_result, regime_result: selection_result)
    monkeypatch.setattr(
        "research.deep_research.build_research_brief",
        lambda **kwargs: {
            "ok": True,
            "ticker": kwargs["ticker"],
            "brief_type": "deep_research",
            "research_summary": f"{kwargs['ticker']} research brief.",
            "research_conviction": {"score": 71.0, "label": "medium"},
            "bull_case": {"points": ["Objective evidence is constructive."]},
            "bear_case": {"points": ["Normal pullback risk."]},
            "key_risks": ["Pullback risk"],
            "raw_context": {},
        },
    )

    result = run_weekly_trade_hunt(include_research_briefs=True, db_path=db_path)

    assert result["ok"] is True
    assert result["decision_result"]["final_recommendations"][0]["research_brief"]["brief_type"] == "deep_research"
    assert "research_brief" not in result["selection_result"]["selected_trades"][0]


def test_weekly_trade_hunt_include_options_attaches_option_alternatives(monkeypatch, tmp_path):
    db_path = str(tmp_path / "brain_options.db")
    init_trade_tracking_db(db_path)

    monkeypatch.setattr("agent.trading_brain.get_default_universe", lambda **kwargs: {"ok": True, "tickers": ["AAPL"], "count": 1, "errors": []})
    monkeypatch.setattr("agent.trading_brain.scan_multi_strategy_candidates", lambda **kwargs: {"ok": True, "profiles_run": ["momentum_breakout"]})
    monkeypatch.setattr("agent.trading_brain.get_open_recommendations", lambda db_path="strategy_library.db": [])
    monkeypatch.setattr("agent.trading_brain.select_weekly_trades", lambda **kwargs: _selection_result(_candidate("AAPL")))
    monkeypatch.setattr("agent.trading_brain.get_market_regime_snapshot", lambda **kwargs: {"ok": True, "regime": "risk_on_uptrend", "summary": "Risk on.", "options_aggressiveness": "normal", "max_trades_adjustment": 1, "trade_aggressiveness": "normal", "risk_flags": []})
    monkeypatch.setattr("agent.trading_brain.apply_regime_to_trade_selection", lambda selection_result, regime_result: selection_result)
    monkeypatch.setattr(
        "agent.trading_brain.scan_options_for_weekly_selection",
        lambda selected_stock_candidates, max_contracts_per_ticker=3: {
            "ok": True,
            "results": [
                {
                    "ticker": "AAPL",
                    "best_option_candidates": [_option_candidate()],
                    "summary": {"contracts_evaluated": 2, "contracts_passed": 1, "message": "ok"},
                    "errors": [],
                }
            ],
            "errors": [],
        },
    )
    monkeypatch.setattr("agent.trading_brain.get_win_loss_record", lambda **kwargs: {"wins": 0, "losses": 0, "win_rate": 0.0})
    monkeypatch.setattr("agent.trading_brain.get_strategy_performance", lambda **kwargs: {"overall": {}})

    result = run_weekly_trade_hunt(include_options=True, db_path=db_path)
    decision = result["decision_result"]["final_recommendations"][0]

    assert result["ok"] is True
    assert result["option_research"]["ok"] is True
    assert len(decision["option_alternatives"]) == 1
    assert decision["preferred_instrument"] == "stock"


def test_prefer_options_true_selects_option_only_when_valid(monkeypatch, tmp_path):
    db_path = str(tmp_path / "brain_prefer_options.db")
    init_trade_tracking_db(db_path)

    monkeypatch.setattr("agent.trading_brain.get_default_universe", lambda **kwargs: {"ok": True, "tickers": ["AAPL"], "count": 1, "errors": []})
    monkeypatch.setattr("agent.trading_brain.scan_multi_strategy_candidates", lambda **kwargs: {"ok": True, "profiles_run": ["momentum_breakout"]})
    monkeypatch.setattr("agent.trading_brain.get_open_recommendations", lambda db_path="strategy_library.db": [])
    monkeypatch.setattr("agent.trading_brain.select_weekly_trades", lambda **kwargs: _selection_result(_candidate("AAPL")))
    monkeypatch.setattr("agent.trading_brain.get_market_regime_snapshot", lambda **kwargs: {"ok": True, "regime": "risk_on_uptrend", "summary": "Risk on.", "options_aggressiveness": "normal", "max_trades_adjustment": 1, "trade_aggressiveness": "normal", "risk_flags": []})
    monkeypatch.setattr("agent.trading_brain.apply_regime_to_trade_selection", lambda selection_result, regime_result: selection_result)
    monkeypatch.setattr(
        "agent.trading_brain.scan_options_for_weekly_selection",
        lambda selected_stock_candidates, max_contracts_per_ticker=3: {
            "ok": True,
            "results": [{"ticker": "AAPL", "best_option_candidates": [_option_candidate()], "summary": {}, "errors": []}],
            "errors": [],
        },
    )
    monkeypatch.setattr("agent.trading_brain.get_win_loss_record", lambda **kwargs: {"wins": 0, "losses": 0, "win_rate": 0.0})
    monkeypatch.setattr("agent.trading_brain.get_strategy_performance", lambda **kwargs: {"overall": {}})

    result = run_weekly_trade_hunt(
        include_options=True,
        prefer_options=True,
        include_portfolio_risk=False,
        include_position_sizing=False,
        db_path=db_path,
    )
    decision = result["decision_result"]["final_recommendations"][0]

    assert result["ok"] is True
    assert decision["preferred_instrument"] == "option"
    assert decision["preferred_option_contract"] == "AAPL260703C00125000"
    assert decision["preferred_option_mispricing_context"]["mispricing_label"] == "attractive_value"


def test_failed_option_candidates_do_not_replace_stock_trade(monkeypatch, tmp_path):
    db_path = str(tmp_path / "brain_bad_option.db")
    init_trade_tracking_db(db_path)

    monkeypatch.setattr("agent.trading_brain.get_default_universe", lambda **kwargs: {"ok": True, "tickers": ["AAPL"], "count": 1, "errors": []})
    monkeypatch.setattr("agent.trading_brain.scan_multi_strategy_candidates", lambda **kwargs: {"ok": True, "profiles_run": ["momentum_breakout"]})
    monkeypatch.setattr("agent.trading_brain.get_open_recommendations", lambda db_path="strategy_library.db": [])
    monkeypatch.setattr("agent.trading_brain.select_weekly_trades", lambda **kwargs: _selection_result(_candidate("AAPL")))
    monkeypatch.setattr("agent.trading_brain.get_market_regime_snapshot", lambda **kwargs: {"ok": True, "regime": "risk_on_uptrend", "summary": "Risk on.", "options_aggressiveness": "normal", "max_trades_adjustment": 1, "trade_aggressiveness": "normal", "risk_flags": []})
    monkeypatch.setattr("agent.trading_brain.apply_regime_to_trade_selection", lambda selection_result, regime_result: selection_result)
    monkeypatch.setattr(
        "agent.trading_brain.scan_options_for_weekly_selection",
        lambda selected_stock_candidates, max_contracts_per_ticker=3: {
            "ok": True,
            "results": [{"ticker": "AAPL", "best_option_candidates": [_option_candidate(passed=False, recommendation_status='rejected')], "summary": {}, "errors": []}],
            "errors": [],
        },
    )
    monkeypatch.setattr("agent.trading_brain.get_win_loss_record", lambda **kwargs: {"wins": 0, "losses": 0, "win_rate": 0.0})
    monkeypatch.setattr("agent.trading_brain.get_strategy_performance", lambda **kwargs: {"overall": {}})

    result = run_weekly_trade_hunt(include_options=True, prefer_options=True, db_path=db_path)
    decision = result["decision_result"]["final_recommendations"][0]

    assert result["ok"] is True
    assert decision["preferred_instrument"] == "stock"
    assert decision["preferred_option_contract"] is None


def test_option_without_approved_risk_is_not_preferred(monkeypatch, tmp_path):
    db_path = str(tmp_path / "brain_option_risk_block.db")
    init_trade_tracking_db(db_path)

    monkeypatch.setattr("agent.trading_brain.get_default_universe", lambda **kwargs: {"ok": True, "tickers": ["AAPL"], "count": 1, "errors": []})
    monkeypatch.setattr("agent.trading_brain.scan_multi_strategy_candidates", lambda **kwargs: {"ok": True, "profiles_run": ["momentum_breakout"]})
    monkeypatch.setattr("agent.trading_brain.get_open_recommendations", lambda db_path="strategy_library.db": [])
    monkeypatch.setattr("agent.trading_brain.select_weekly_trades", lambda **kwargs: _selection_result(_candidate("AAPL")))
    monkeypatch.setattr("agent.trading_brain.get_market_regime_snapshot", lambda **kwargs: {"ok": True, "regime": "risk_on_uptrend", "summary": "Risk on.", "options_aggressiveness": "normal", "max_trades_adjustment": 1, "trade_aggressiveness": "normal", "risk_flags": []})
    monkeypatch.setattr("agent.trading_brain.apply_regime_to_trade_selection", lambda selection_result, regime_result: selection_result)
    blocked_option = _option_candidate(
        option_trade_risk={
            "ok": False,
            "approved": False,
            "status": "blocked",
            "errors": ["Usable Greeks are unavailable."],
            "warnings": [],
        },
        options_research_status="blocked",
    )
    monkeypatch.setattr(
        "agent.trading_brain.scan_options_for_weekly_selection",
        lambda selected_stock_candidates, max_contracts_per_ticker=3: {
            "ok": True,
            "results": [{"ticker": "AAPL", "best_option_candidates": [blocked_option], "summary": {}, "errors": []}],
            "best_option_candidates": [blocked_option],
            "errors": [],
        },
    )
    monkeypatch.setattr("agent.trading_brain.get_win_loss_record", lambda **kwargs: {"wins": 0, "losses": 0, "win_rate": 0.0})
    monkeypatch.setattr("agent.trading_brain.get_strategy_performance", lambda **kwargs: {"overall": {}})

    result = run_weekly_trade_hunt(
        include_options=True,
        prefer_options=True,
        include_portfolio_risk=False,
        include_position_sizing=False,
        db_path=db_path,
    )
    decision = result["decision_result"]["final_recommendations"][0]

    assert decision["preferred_instrument"] == "stock"
    assert decision["preferred_option_contract"] is None
    assert "greeks" in (decision["option_selection_reason"] or "").lower()


def test_cheap_but_low_probability_option_is_not_preferred(monkeypatch, tmp_path):
    db_path = str(tmp_path / "brain_low_probability_option.db")
    init_trade_tracking_db(db_path)

    monkeypatch.setattr("agent.trading_brain.get_default_universe", lambda **kwargs: {"ok": True, "tickers": ["AAPL"], "count": 1, "errors": []})
    monkeypatch.setattr("agent.trading_brain.scan_multi_strategy_candidates", lambda **kwargs: {"ok": True, "profiles_run": ["momentum_breakout"]})
    monkeypatch.setattr("agent.trading_brain.get_open_recommendations", lambda db_path="strategy_library.db": [])
    monkeypatch.setattr("agent.trading_brain.select_weekly_trades", lambda **kwargs: _selection_result(_candidate("AAPL")))
    monkeypatch.setattr("agent.trading_brain.get_market_regime_snapshot", lambda **kwargs: {"ok": True, "regime": "risk_on_uptrend", "summary": "Risk on.", "options_aggressiveness": "normal", "max_trades_adjustment": 1, "trade_aggressiveness": "normal", "risk_flags": []})
    monkeypatch.setattr("agent.trading_brain.apply_regime_to_trade_selection", lambda selection_result, regime_result: selection_result)
    monkeypatch.setattr(
        "agent.trading_brain.scan_options_for_weekly_selection",
        lambda selected_stock_candidates, max_contracts_per_ticker=3: {
            "ok": True,
            "results": [
                {
                    "ticker": "AAPL",
                    "best_option_candidates": [
                        _option_candidate(
                            mispricing_label="cheap_but_low_probability",
                            mispricing_score=63.0,
                            mispricing_context={
                                "ok": True,
                                "mispricing_label": "cheap_but_low_probability",
                                "mispricing_score": 63.0,
                                "target_exceeds_breakeven": False,
                                "warnings": ["low_probability_delta"],
                                "explanation": "Cheap but low probability.",
                            },
                        )
                    ],
                    "summary": {},
                    "errors": [],
                }
            ],
            "errors": [],
        },
    )
    monkeypatch.setattr("agent.trading_brain.get_win_loss_record", lambda **kwargs: {"wins": 0, "losses": 0, "win_rate": 0.0})
    monkeypatch.setattr("agent.trading_brain.get_strategy_performance", lambda **kwargs: {"overall": {}})

    result = run_weekly_trade_hunt(include_options=True, prefer_options=True, db_path=db_path)
    decision = result["decision_result"]["final_recommendations"][0]

    assert result["ok"] is True
    assert decision["preferred_instrument"] == "stock"
    assert "probability" in (decision["option_selection_reason"] or "").lower()


def test_incomplete_option_candidate_does_not_get_logged_as_option(monkeypatch, tmp_path):
    db_path = str(tmp_path / "brain_incomplete_option.db")
    init_trade_tracking_db(db_path)

    monkeypatch.setattr("agent.trading_brain.get_default_universe", lambda **kwargs: {"ok": True, "tickers": ["AAPL"], "count": 1, "errors": []})
    monkeypatch.setattr("agent.trading_brain.scan_multi_strategy_candidates", lambda **kwargs: {"ok": True, "profiles_run": ["momentum_breakout"]})
    monkeypatch.setattr("agent.trading_brain.get_open_recommendations", lambda db_path="strategy_library.db": [])
    monkeypatch.setattr("agent.trading_brain.select_weekly_trades", lambda **kwargs: _selection_result(_candidate("AAPL")))
    monkeypatch.setattr("agent.trading_brain.get_market_regime_snapshot", lambda **kwargs: {"ok": True, "regime": "risk_on_uptrend", "summary": "Risk on.", "options_aggressiveness": "normal", "max_trades_adjustment": 1, "trade_aggressiveness": "normal", "risk_flags": []})
    monkeypatch.setattr("agent.trading_brain.apply_regime_to_trade_selection", lambda selection_result, regime_result: selection_result)
    monkeypatch.setattr(
        "agent.trading_brain.scan_options_for_weekly_selection",
        lambda selected_stock_candidates, max_contracts_per_ticker=3: {
            "ok": True,
            "results": [{"ticker": "AAPL", "best_option_candidates": [_option_candidate(option_contract=None, expiration=None)], "summary": {}, "errors": []}],
            "errors": [],
        },
    )
    monkeypatch.setattr("agent.trading_brain.get_win_loss_record", lambda **kwargs: {"wins": 0, "losses": 0, "win_rate": 0.0})
    monkeypatch.setattr("agent.trading_brain.get_strategy_performance", lambda **kwargs: {"overall": {}})

    result = run_weekly_trade_hunt(
        include_options=True,
        prefer_options=True,
        auto_log=True,
        db_path=db_path,
    )

    assert result["ok"] is True
    decision = result["decision_result"]["final_recommendations"][0]
    assert decision["preferred_instrument"] == "stock"

    with sqlite3.connect(db_path) as conn:
        rows = conn.execute("SELECT ticker, asset_type, option_contract, expiration FROM trade_recommendations ORDER BY id ASC").fetchall()
    assert rows == [("AAPL", "stock", None, None)]


def test_trading_brain_includes_market_regime_when_enabled(monkeypatch, tmp_path):
    db_path = str(tmp_path / "brain_regime_enabled.db")
    init_trade_tracking_db(db_path)

    monkeypatch.setattr("agent.trading_brain.get_default_universe", lambda **kwargs: {"ok": True, "tickers": ["AAPL"], "count": 1, "errors": []})
    monkeypatch.setattr("agent.trading_brain.scan_multi_strategy_candidates", lambda **kwargs: {"ok": True, "profiles_run": ["momentum_breakout"]})
    monkeypatch.setattr("agent.trading_brain.get_open_recommendations", lambda **kwargs: [])
    monkeypatch.setattr("agent.trading_brain.select_weekly_trades", lambda **kwargs: _selection_result(_candidate("AAPL")))
    monkeypatch.setattr(
        "agent.trading_brain.get_market_regime_snapshot",
        lambda **kwargs: {
            "ok": True,
            "regime": "neutral_chop",
            "summary": "Neutral chop.",
            "options_aggressiveness": "conservative",
            "max_trades_adjustment": -2,
            "trade_aggressiveness": "low",
            "risk_flags": ["Market breadth is mixed."],
        },
    )
    monkeypatch.setattr("agent.trading_brain.apply_regime_to_trade_selection", lambda selection_result, regime_result: {**selection_result, "market_regime": regime_result})
    monkeypatch.setattr("agent.trading_brain.get_win_loss_record", lambda **kwargs: {"wins": 0, "losses": 0, "win_rate": 0.0})
    monkeypatch.setattr("agent.trading_brain.get_strategy_performance", lambda **kwargs: {"overall": {}})

    result = run_weekly_trade_hunt(include_market_regime=True, db_path=db_path)

    assert result["ok"] is True
    assert result["market_regime"]["regime"] == "neutral_chop"
    assert result["decision_result"]["market_regime"]["regime"] == "neutral_chop"


def test_ticker_review_scope_does_not_require_market_breadth(monkeypatch, tmp_path):
    db_path = str(tmp_path / "brain_regime_ticker_no_breadth.db")
    init_trade_tracking_db(db_path)
    captured = {}

    monkeypatch.setattr("agent.trading_brain.get_default_universe", lambda **kwargs: {"ok": True, "tickers": ["AAPL"], "count": 1, "errors": []})
    monkeypatch.setattr("agent.trading_brain.scan_multi_strategy_candidates", lambda **kwargs: {"ok": True, "profiles_run": ["momentum_breakout"]})
    monkeypatch.setattr("agent.trading_brain.get_open_recommendations", lambda **kwargs: [])
    monkeypatch.setattr("agent.trading_brain.select_weekly_trades", lambda **kwargs: _selection_result(_candidate("AAPL")))
    monkeypatch.setattr("agent.trading_brain.get_win_loss_record", lambda **kwargs: {"wins": 0, "losses": 0, "win_rate": 0.0})
    monkeypatch.setattr("agent.trading_brain.get_strategy_performance", lambda **kwargs: {"overall": {}})

    def fake_regime(**kwargs):
        captured.update(kwargs)
        return {
            "ok": True,
            "regime": "neutral_chop",
            "summary": "Neutral chop.",
            "options_aggressiveness": "normal",
            "max_trades_adjustment": 0,
            "trade_aggressiveness": "normal",
            "risk_flags": [],
            "warnings": [],
        }

    monkeypatch.setattr("agent.trading_brain.get_market_regime_snapshot", fake_regime)

    result = run_weekly_trade_hunt(
        include_market_regime=True,
        include_portfolio_risk=False,
        include_relative_strength=False,
        db_path=db_path,
    )

    assert result["ok"] is True
    assert captured["include_breadth"] is False
    assert result["market_regime"]["regime"] == "neutral_chop"


def test_broad_scan_uses_bounded_market_breadth(monkeypatch, tmp_path):
    db_path = str(tmp_path / "brain_regime_broad_breadth.db")
    init_trade_tracking_db(db_path)
    captured = {}

    monkeypatch.setattr("agent.trading_brain.get_default_universe", lambda **kwargs: {"ok": True, "tickers": ["AAPL", "MSFT"], "count": 2, "errors": []})
    monkeypatch.setattr("agent.trading_brain.scan_multi_strategy_candidates", lambda **kwargs: {"ok": True, "profiles_run": ["momentum_breakout"]})
    monkeypatch.setattr("agent.trading_brain.get_open_recommendations", lambda **kwargs: [])
    monkeypatch.setattr("agent.trading_brain.select_weekly_trades", lambda **kwargs: _selection_result(_candidate("AAPL")))
    monkeypatch.setattr("agent.trading_brain.get_win_loss_record", lambda **kwargs: {"wins": 0, "losses": 0, "win_rate": 0.0})
    monkeypatch.setattr("agent.trading_brain.get_strategy_performance", lambda **kwargs: {"overall": {}})

    def fake_regime(**kwargs):
        captured.update(kwargs)
        return {
            "ok": True,
            "regime": "neutral_chop",
            "summary": "Neutral chop.",
            "options_aggressiveness": "normal",
            "max_trades_adjustment": 0,
            "trade_aggressiveness": "normal",
            "risk_flags": [],
            "warnings": [],
        }

    monkeypatch.setattr("agent.trading_brain.get_market_regime_snapshot", fake_regime)

    result = run_weekly_trade_hunt(
        include_market_regime=True,
        include_portfolio_risk=False,
        include_relative_strength=False,
        db_path=db_path,
    )

    assert result["ok"] is True
    assert captured["include_breadth"] is True
    assert captured["breadth_sample_size"] == 5


def test_market_regime_timeout_is_warning_not_ranking_unavailable(monkeypatch, tmp_path):
    db_path = str(tmp_path / "brain_regime_timeout.db")
    init_trade_tracking_db(db_path)
    monkeypatch.setenv("MARKET_REGIME_TIMEOUT_SECONDS", "0.01")

    monkeypatch.setattr("agent.trading_brain.get_default_universe", lambda **kwargs: {"ok": True, "tickers": ["AAPL"], "count": 1, "errors": []})
    monkeypatch.setattr("agent.trading_brain.scan_multi_strategy_candidates", lambda **kwargs: {"ok": True, "profiles_run": ["momentum_breakout"]})
    monkeypatch.setattr("agent.trading_brain.get_open_recommendations", lambda **kwargs: [])
    monkeypatch.setattr("agent.trading_brain.select_weekly_trades", lambda **kwargs: _selection_result(_candidate("AAPL")))
    monkeypatch.setattr("agent.trading_brain.get_win_loss_record", lambda **kwargs: {"wins": 0, "losses": 0, "win_rate": 0.0})
    monkeypatch.setattr("agent.trading_brain.get_strategy_performance", lambda **kwargs: {"overall": {}})

    def slow_regime(**kwargs):
        time.sleep(0.2)
        return {"ok": True, "regime": "neutral_chop", "summary": "Should not block."}

    monkeypatch.setattr("agent.trading_brain.get_market_regime_snapshot", slow_regime)

    started = time.monotonic()
    result = run_weekly_trade_hunt(
        include_market_regime=True,
        include_portfolio_risk=False,
        include_relative_strength=False,
        db_path=db_path,
    )
    duration = time.monotonic() - started

    assert duration < 0.2
    assert result["ok"] is True
    assert result["market_regime"]["timed_out"] is True
    assert result["market_regime"]["ok"] is False
    assert result["summary"]["selected_count"] >= 0
    assert any("Market regime context timed out" in warning for warning in result["warnings"])
    assert "ranking_unavailable" not in str(result)


def test_trading_brain_preserves_old_behavior_when_market_regime_disabled(monkeypatch, tmp_path):
    db_path = str(tmp_path / "brain_regime_disabled.db")
    init_trade_tracking_db(db_path)

    monkeypatch.setattr("agent.trading_brain.get_default_universe", lambda **kwargs: {"ok": True, "tickers": ["AAPL"], "count": 1, "errors": []})
    monkeypatch.setattr("agent.trading_brain.scan_multi_strategy_candidates", lambda **kwargs: {"ok": True, "profiles_run": ["momentum_breakout"]})
    monkeypatch.setattr("agent.trading_brain.get_open_recommendations", lambda **kwargs: [])
    monkeypatch.setattr("agent.trading_brain.select_weekly_trades", lambda **kwargs: _selection_result(_candidate("AAPL")))
    monkeypatch.setattr("agent.trading_brain.get_win_loss_record", lambda **kwargs: {"wins": 0, "losses": 0, "win_rate": 0.0})
    monkeypatch.setattr("agent.trading_brain.get_strategy_performance", lambda **kwargs: {"overall": {}})

    result = run_weekly_trade_hunt(include_market_regime=False, db_path=db_path)

    assert result["ok"] is True
    assert result["market_regime"] is None


def test_trading_brain_includes_relative_strength_context_when_enabled(monkeypatch, tmp_path):
    db_path = str(tmp_path / "brain_relative_strength_enabled.db")
    init_trade_tracking_db(db_path)

    monkeypatch.setattr("agent.trading_brain.get_default_universe", lambda **kwargs: {"ok": True, "tickers": ["AAPL"], "count": 1, "errors": []})
    monkeypatch.setattr("agent.trading_brain.scan_multi_strategy_candidates", lambda **kwargs: {"ok": True, "profiles_run": ["momentum_breakout"]})
    monkeypatch.setattr("agent.trading_brain.get_open_recommendations", lambda **kwargs: [])
    monkeypatch.setattr("agent.trading_brain.select_weekly_trades", lambda **kwargs: _selection_result(_candidate("AAPL")))
    monkeypatch.setattr("agent.trading_brain.get_market_regime_snapshot", lambda **kwargs: {"ok": True, "regime": "risk_on_uptrend", "summary": "Risk on.", "options_aggressiveness": "normal", "max_trades_adjustment": 1, "trade_aggressiveness": "normal", "risk_flags": []})
    monkeypatch.setattr("agent.trading_brain.apply_regime_to_trade_selection", lambda selection_result, regime_result: selection_result)
    monkeypatch.setattr(
        "agent.trading_brain.get_relative_strength_snapshot",
        lambda **kwargs: {
            "ok": True,
            "ticker": "AAPL",
            "relative_strength_label": "market_leader",
            "relative_strength_score": 88.0,
            "risk_flags": [],
            "summary": "Market leader.",
        },
    )
    monkeypatch.setattr("agent.trading_brain.get_win_loss_record", lambda **kwargs: {"wins": 0, "losses": 0, "win_rate": 0.0})
    monkeypatch.setattr("agent.trading_brain.get_strategy_performance", lambda **kwargs: {"overall": {}})

    result = run_weekly_trade_hunt(include_relative_strength=True, db_path=db_path)

    assert result["ok"] is True
    decision = result["decision_result"]["final_recommendations"][0]
    assert decision["relative_strength_context"]["relative_strength_label"] in {"outperforming", "market_leader"}


def test_trading_brain_preserves_old_behavior_when_relative_strength_disabled(monkeypatch, tmp_path):
    db_path = str(tmp_path / "brain_relative_strength_disabled.db")
    init_trade_tracking_db(db_path)

    monkeypatch.setattr("agent.trading_brain.get_default_universe", lambda **kwargs: {"ok": True, "tickers": ["AAPL"], "count": 1, "errors": []})
    monkeypatch.setattr("agent.trading_brain.scan_multi_strategy_candidates", lambda **kwargs: {"ok": True, "profiles_run": ["momentum_breakout"]})
    monkeypatch.setattr("agent.trading_brain.get_open_recommendations", lambda **kwargs: [])
    monkeypatch.setattr("agent.trading_brain.select_weekly_trades", lambda **kwargs: _selection_result(_candidate("AAPL")))
    monkeypatch.setattr("agent.trading_brain.get_market_regime_snapshot", lambda **kwargs: {"ok": True, "regime": "risk_on_uptrend", "summary": "Risk on.", "options_aggressiveness": "normal", "max_trades_adjustment": 1, "trade_aggressiveness": "normal", "risk_flags": []})
    monkeypatch.setattr("agent.trading_brain.apply_regime_to_trade_selection", lambda selection_result, regime_result: selection_result)
    monkeypatch.setattr("agent.trading_brain.get_win_loss_record", lambda **kwargs: {"wins": 0, "losses": 0, "win_rate": 0.0})
    monkeypatch.setattr("agent.trading_brain.get_strategy_performance", lambda **kwargs: {"overall": {}})

    result = run_weekly_trade_hunt(include_relative_strength=False, db_path=db_path)

    assert result["ok"] is True
    decision = result["decision_result"]["final_recommendations"][0]
    assert decision["relative_strength_context"]["relative_strength_label"] == "outperforming"
