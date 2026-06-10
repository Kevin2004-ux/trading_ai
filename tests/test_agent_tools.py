from tools.agent_tools import (
    build_trade_review_tool,
    calculate_position_size_tool,
    evaluate_option_mispricing_tool,
    find_similar_setups_tool,
    generate_report_tool,
    get_catalyst_brain_tool,
    get_candidate_details_tool,
    get_deep_research_brief_tool,
    get_earnings_transcript_brain_tool,
    get_market_regime_tool,
    get_open_recommendations_tool,
    get_portfolio_risk_tool,
    get_relative_strength_tool,
    get_sec_filing_brain_tool,
    get_trade_reviews_tool,
    scan_options_for_candidate_tool,
    get_statistical_brain_tool,
    get_strategy_performance_tool,
    get_win_loss_record_tool,
    log_recommendation_tool,
    review_closed_trades_tool,
    run_paper_trading_tool,
    run_trading_brain_tool,
    scan_market_for_weekly_trades_tool,
    scan_candidates_tool,
    search_trade_memory_tool,
    store_trade_memory_tool,
    update_outcomes_tool,
)
from tracking.trade_logger import init_trade_tracking_db


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


def test_scan_candidates_tool_returns_structured_output(monkeypatch):
    monkeypatch.setattr(
        "tools.agent_tools.scan_multi_strategy_candidates",
        lambda **kwargs: {
            "ok": True,
            "scanner_run_id": 12,
            "universe": "custom",
            "timestamp": "2026-06-05T00:00:00+00:00",
            "profiles_run": ["momentum_breakout"],
            "total_tickers_scanned": 2,
            "total_profile_evaluations": 2,
            "total_recommendable": 1,
            "total_watchlist": 0,
            "total_rejected": 1,
            "best_candidates": [{"ticker": "AAPL"}],
            "candidates_by_profile": {"momentum_breakout": [{"ticker": "AAPL"}]},
            "watchlist_candidates": [],
            "rejected_candidates": [{"ticker": "TSLA"}],
            "errors": [],
        },
    )

    result = scan_candidates_tool(["AAPL", "TSLA"])

    assert result["ok"] is True
    assert result["tool"] == "scan_candidates_tool"
    assert result["data"]["total_recommendable"] == 1


def test_get_candidate_details_tool_returns_candidate_and_constraint_data(monkeypatch):
    monkeypatch.setattr(
        "tools.agent_tools.get_market_snapshot",
        lambda ticker, lookback_days=180: {
            "ok": True,
            "ticker": ticker,
            "source": "polygon",
            "timestamp": "2026-06-05T00:00:00+00:00",
            "data": {
                "quote": {"last_price": 120.0},
                "technical_snapshot": {
                    "ok": True,
                    "current_price": 120.0,
                    "sma_20": 114.0,
                    "sma_50": 108.0,
                    "high_20": 121.0,
                    "atr_14": 2.0,
                    "average_volume_20": 2_000_000,
                    "relative_volume": 1.6,
                    "atr_percent": 3.0,
                },
                "data_freshness": {"ok": True, "freshness_label": "fresh"},
            },
            "error": None,
        },
    )

    result = get_candidate_details_tool("AAPL")

    assert result["ok"] is True
    assert result["tool"] == "get_candidate_details_tool"
    assert result["data"]["candidate"]["ticker"] == "AAPL"
    assert "constraint_result" in result["data"]


def test_log_recommendation_tool_rejects_missing_stop_loss():
    result = log_recommendation_tool(
        ticker="AAPL",
        asset_type="stock",
        direction="long",
        strategy="test",
        entry_price=100.0,
        target_price=110.0,
        stop_loss=None,
        risk_reward=2.5,
        constraint_results=_recommendable_constraints(),
    )

    assert result["ok"] is False
    assert "stop_loss" in result["error"]


def test_log_recommendation_tool_rejects_failed_constraints():
    constraints = _recommendable_constraints()
    constraints["passed"] = False
    constraints["recommendation_status"] = "rejected"

    result = log_recommendation_tool(
        ticker="AAPL",
        asset_type="stock",
        direction="long",
        strategy="test",
        entry_price=100.0,
        target_price=110.0,
        stop_loss=95.0,
        risk_reward=2.5,
        constraint_results=constraints,
    )

    assert result["ok"] is False
    assert "Failed constraints" in result["error"]


def test_log_recommendation_tool_rejects_risk_reward_below_two():
    result = log_recommendation_tool(
        ticker="AAPL",
        asset_type="stock",
        direction="long",
        strategy="test",
        entry_price=100.0,
        target_price=103.0,
        stop_loss=99.0,
        risk_reward=1.5,
        constraint_results=_recommendable_constraints(),
    )

    assert result["ok"] is False
    assert "risk_reward" in result["error"]


def test_log_recommendation_tool_logs_valid_recommendation_into_temp_sqlite(tmp_path):
    db_path = str(tmp_path / "agent_tools.db")
    init_trade_tracking_db(db_path)

    result = log_recommendation_tool(
        ticker="AAPL",
        asset_type="stock",
        direction="long",
        strategy="test_strategy",
        entry_price=100.0,
        target_price=110.0,
        stop_loss=95.0,
        setup_type="momentum_breakout",
        risk_reward=2.0,
        score=91.5,
        thesis="Passed all objective rules.",
        constraint_results=_recommendable_constraints(),
        db_path=db_path,
    )

    assert result["ok"] is True
    assert result["data"]["recommendation_id"] is not None
    assert result["data"]["recommendation"]["ticker"] == "AAPL"


def test_get_open_recommendations_tool_returns_logged_open_trades(tmp_path):
    db_path = str(tmp_path / "agent_tools.db")
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

    result = get_open_recommendations_tool(db_path=db_path)

    assert result["ok"] is True
    assert len(result["data"]["recommendations"]) == 1
    assert result["data"]["recommendations"][0]["ticker"] == "AAPL"


def test_get_win_loss_record_tool_returns_structured_performance_data(tmp_path):
    db_path = str(tmp_path / "agent_tools.db")
    init_trade_tracking_db(db_path)

    result = get_win_loss_record_tool(db_path=db_path)

    assert result["ok"] is True
    assert result["tool"] == "get_win_loss_record_tool"
    assert "total_recommendations" in result["data"]


def test_get_portfolio_risk_tool_returns_structured_output(monkeypatch):
    monkeypatch.setattr("tools.agent_tools.get_open_recommendations", lambda db_path="strategy_library.db": [])
    monkeypatch.setattr(
        "tools.agent_tools.apply_portfolio_risk_limits",
        lambda proposed_trades, existing_open_trades=None, account_size=10000.0, config=None: {
            "ok": True,
            "approved_trades": proposed_trades[:1],
            "rejected_trades": [{"ticker": "MSFT", "rejection_reason": "Trade would exceed max_same_sector_trades."}],
            "risk_summary": {"message": "Portfolio risk check completed."},
        },
    )

    result = get_portfolio_risk_tool(
        proposed_trades=[
            {"ticker": "AAPL", "recommendation_status": "recommendable", "passed": True},
            {"ticker": "MSFT", "recommendation_status": "recommendable", "passed": True},
        ],
        account_size=15000.0,
    )

    assert result["ok"] is True
    assert result["tool"] == "get_portfolio_risk_tool"
    assert result["data"]["approved_trades"][0]["ticker"] == "AAPL"


def test_calculate_position_size_tool_returns_standard_envelope():
    result = calculate_position_size_tool(
        trade={"ticker": "AAPL", "asset_type": "stock", "entry_price": 100.0, "stop_loss": 95.0},
        account_size=10000.0,
        risk_mode="normal",
    )

    assert result["ok"] is True
    assert result["tool"] == "calculate_position_size_tool"
    assert result["data"]["shares"] == 20


def test_search_trade_memory_tool_returns_standard_envelope(monkeypatch):
    monkeypatch.setattr(
        "tools.agent_tools.search_memory",
        lambda query, top_k=5: {
            "ok": True,
            "source": "mock",
            "query": query,
            "namespace": "trading_ai",
            "matches": [{"memory_id": "m1", "score": 0.9, "metadata": {"ticker": "AAPL"}, "text": "Similar setup."}],
            "error": None,
        },
    )

    result = search_trade_memory_tool("AAPL breakout", top_k=3)

    assert result["ok"] is True
    assert result["tool"] == "search_trade_memory_tool"
    assert result["data"]["matches"][0]["memory_id"] == "m1"


def test_store_trade_memory_tool_returns_standard_envelope(monkeypatch):
    monkeypatch.setattr(
        "tools.agent_tools.store_memory_item",
        lambda item, item_type="manual_note": {
            "ok": True,
            "source": "mock",
            "memory_id": "note-1",
            "namespace": "trading_ai",
            "item_type": item_type,
            "metadata": {"ticker": item["ticker"]},
            "error": None,
        },
    )

    result = store_trade_memory_tool({"ticker": "AAPL", "note": "Breakout thesis"}, item_type="manual_note")

    assert result["ok"] is True
    assert result["tool"] == "store_trade_memory_tool"
    assert result["data"]["memory_id"] == "note-1"


def test_find_similar_setups_tool_returns_standard_envelope(monkeypatch):
    monkeypatch.setattr(
        "tools.agent_tools.find_similar_setups",
        lambda candidate_or_trade, top_k=5: {
            "ok": True,
            "source": "mock",
            "query": "AAPL setup",
            "matches": [{"memory_id": "m1", "score": 0.9, "metadata": {"ticker": "AAPL"}, "text": "Similar."}],
            "warnings": ["Semantic memory is qualitative context only."],
            "label": "qualitative_context_only",
            "error": None,
        },
    )

    result = find_similar_setups_tool({"ticker": "AAPL"}, top_k=2)

    assert result["ok"] is True
    assert result["tool"] == "find_similar_setups_tool"
    assert result["data"]["label"] == "qualitative_context_only"


def test_build_trade_review_tool_returns_standard_envelope(monkeypatch):
    monkeypatch.setattr(
        "tools.agent_tools.get_recommendation",
        lambda recommendation_id, db_path="strategy_library.db": {
            "id": recommendation_id,
            "ticker": "AAPL",
            "status": "win",
            "outcome": "win",
            "thesis": "Valid breakout.",
            "invalidation": "Stop hit.",
            "entry_price": 100.0,
            "target_price": 110.0,
            "stop_loss": 95.0,
            "risk_reward": 2.0,
            "constraint_results_json": {"passed": True, "recommendation_status": "recommendable"},
        },
    )
    monkeypatch.setattr(
        "tools.agent_tools.build_trade_review",
        lambda recommendation, db_path="strategy_library.db": {
            "ok": True,
            "recommendation_id": recommendation["id"],
            "ticker": recommendation["ticker"],
            "trade_quality": {"label": "good_process", "score": 88},
            "error": None,
        },
    )

    result = build_trade_review_tool(1)

    assert result["ok"] is True
    assert result["tool"] == "build_trade_review_tool"
    assert result["data"]["recommendation_id"] == 1


def test_review_closed_trades_tool_returns_standard_envelope(monkeypatch):
    monkeypatch.setattr(
        "tools.agent_tools.review_closed_trades",
        lambda db_path="strategy_library.db", store_memory=False: {
            "ok": True,
            "reviewed_count": 1,
            "skipped_count": 0,
            "reviews": [{"recommendation_id": 1}],
            "errors": [],
        },
    )

    result = review_closed_trades_tool(store_memory=True)

    assert result["ok"] is True
    assert result["tool"] == "review_closed_trades_tool"
    assert result["data"]["reviewed_count"] == 1


def test_get_trade_reviews_tool_returns_standard_envelope(monkeypatch):
    monkeypatch.setattr(
        "tools.agent_tools.get_trade_reviews",
        lambda recommendation_id=None, ticker=None, db_path="strategy_library.db": {
            "ok": True,
            "count": 1,
            "reviews": [{"recommendation_id": recommendation_id, "ticker": ticker or "AAPL"}],
            "error": None,
        },
    )

    result = get_trade_reviews_tool(recommendation_id=1)

    assert result["ok"] is True
    assert result["tool"] == "get_trade_reviews_tool"
    assert result["data"]["count"] == 1


def test_generate_report_tool_returns_standard_envelope(monkeypatch):
    monkeypatch.setattr(
        "tools.agent_tools.generate_full_paper_trading_report",
        lambda db_path="strategy_library.db", format="markdown": {
            "ok": True,
            "report_type": "full_paper_trading",
            "format": format,
            "title": "Full Paper Trading Report",
            "summary": "Summary",
            "sections": [],
            "markdown": "# Full Paper Trading Report",
            "data_quality": {"missing_sections": [], "warnings": []},
            "error": None,
        },
    )

    result = generate_report_tool("full_paper_trading", format="markdown")

    assert result["ok"] is True
    assert result["tool"] == "generate_report_tool"
    assert result["data"]["report_type"] == "full_paper_trading"


def test_run_trading_brain_tool_forwards_portfolio_risk_flags(monkeypatch):
    captured = {}

    monkeypatch.setattr(
        "tools.agent_tools.run_weekly_trade_hunt",
        lambda **kwargs: captured.update(kwargs) or {"ok": True, "mode": "weekly_trade_hunt", "decision_result": {}, "errors": []},
    )

    result = run_trading_brain_tool(
        mode="weekly_trade_hunt",
        include_portfolio_risk=False,
        include_position_sizing=False,
        include_memory_context=False,
        store_memory=True,
        account_size=25000.0,
        risk_mode="conservative",
    )

    assert result["ok"] is True
    assert captured["include_portfolio_risk"] is False
    assert captured["include_position_sizing"] is False
    assert captured["include_memory_context"] is False
    assert captured["store_memory"] is True
    assert captured["account_size"] == 25000.0
    assert captured["risk_mode"] == "conservative"


def test_update_outcomes_tool_calls_outcome_grader_and_returns_structured_output(monkeypatch):
    monkeypatch.setattr(
        "tools.agent_tools.update_open_recommendations",
        lambda db_path="strategy_library.db": {
            "ok": True,
            "checked": 2,
            "updated": 1,
            "still_open": 1,
            "manual_review": 0,
            "errors": [],
            "results": [{"recommendation_id": 1, "outcome": "win"}],
        },
    )

    result = update_outcomes_tool()

    assert result["ok"] is True
    assert result["tool"] == "update_outcomes_tool"
    assert result["data"]["updated"] == 1


def test_get_strategy_performance_tool_returns_structured_output(tmp_path):
    db_path = str(tmp_path / "agent_tools.db")
    init_trade_tracking_db(db_path)

    result = get_strategy_performance_tool(db_path=db_path)

    assert result["ok"] is True
    assert result["tool"] == "get_strategy_performance_tool"
    assert "overall" in result["data"]


def test_get_statistical_brain_tool_returns_structured_data(monkeypatch):
    monkeypatch.setattr(
        "tools.agent_tools.analyze_setup_performance",
        lambda db_path="strategy_library.db": {"ok": True, "groups": [{"setup_type": "momentum_breakout"}]},
    )
    monkeypatch.setattr(
        "tools.agent_tools.analyze_ticker_history",
        lambda ticker, db_path="strategy_library.db": {"ok": True, "ticker": ticker, "historical_edge": "positive"},
    )
    monkeypatch.setattr(
        "tools.agent_tools.analyze_profile_performance",
        lambda scan_profile=None, db_path="strategy_library.db": {"ok": True, "profiles": [{"scan_profile": scan_profile or "momentum_breakout"}]},
    )

    result = get_statistical_brain_tool(ticker="AAPL", setup_type="momentum_breakout", scan_profile="momentum_breakout")

    assert result["ok"] is True
    assert result["tool"] == "get_statistical_brain_tool"
    assert result["data"]["ticker_history"]["ticker"] == "AAPL"


def test_evaluate_option_mispricing_tool_returns_structured_output():
    result = evaluate_option_mispricing_tool(
        option_candidate={
            "option_contract": "O:AAPL260703C00125000",
            "ticker": "O:AAPL260703C00125000",
            "underlying_ticker": "AAPL",
            "option_type": "call",
            "strike": 125.0,
            "days_to_expiration": 26,
            "mid": 3.9,
            "bid": 3.8,
            "ask": 4.0,
            "volume": 450,
            "open_interest": 1600,
            "implied_volatility": 0.32,
            "delta": 0.51,
            "spread_percent": 0.05,
            "breakeven_price": 128.9,
            "breakeven_move_percent": (128.9 - 120.0) / 120.0,
        },
        underlying_candidate={
            "ticker": "AAPL",
            "current_price": 120.0,
            "entry_price": 120.0,
            "target_price": 145.0,
            "bars": [{"close": 100.0 + index} for index in range(25)],
        },
        historical_volatility=0.28,
    )

    assert result["ok"] is True
    assert result["tool"] == "evaluate_option_mispricing_tool"
    assert result["data"]["mispricing_label"] in {
        "attractive_value",
        "fair_value",
        "overpriced",
        "high_iv_risky",
        "cheap_but_low_probability",
        "mispricing_unknown",
    }


def test_scan_market_for_weekly_trades_tool_returns_structured_output(monkeypatch):
    monkeypatch.setattr(
        "tools.agent_tools.get_default_universe",
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
        "tools.agent_tools.scan_multi_strategy_candidates",
        lambda **kwargs: {
            "ok": True,
            "best_candidates": [{"ticker": "AAPL", "recommendation_status": "recommendable"}],
            "watchlist_candidates": [{"ticker": "MSFT", "recommendation_status": "watchlist"}],
            "errors": [],
        },
    )
    monkeypatch.setattr("tools.agent_tools.get_open_recommendations", lambda db_path="strategy_library.db": [])
    monkeypatch.setattr(
        "tools.agent_tools.select_weekly_trades",
        lambda **kwargs: {
            "ok": True,
            "timestamp": "2026-06-05T00:00:00+00:00",
            "selected_trades": [{"ticker": "AAPL"}],
            "watchlist_alternatives": [{"ticker": "MSFT"}],
            "rejected_for_portfolio_limits": [],
            "selection_summary": {"selected_count": 1, "watchlist_count": 1, "message": "Only one trade qualified."},
            "errors": [],
        },
    )

    result = scan_market_for_weekly_trades_tool()

    assert result["ok"] is True
    assert result["tool"] == "scan_market_for_weekly_trades_tool"
    assert result["data"]["universe_result"]["count"] == 2
    assert result["data"]["selection_result"]["selected_trades"][0]["ticker"] == "AAPL"


def test_get_catalyst_brain_tool_returns_structured_data(monkeypatch):
    monkeypatch.setattr(
        "tools.agent_tools.get_news_snapshot",
        lambda ticker, lookback_days=7: {"ok": True, "ticker": ticker, "source": "fmp", "timestamp": "x", "lookback_days": lookback_days, "items": [], "error": None},
    )
    monkeypatch.setattr(
        "tools.agent_tools.get_earnings_snapshot",
        lambda ticker: {"ok": True, "ticker": ticker, "source": "fmp", "timestamp": "x", "earnings_date": None, "days_until_earnings": 20, "is_earnings_risk": False, "error": None},
    )
    monkeypatch.setattr(
        "tools.agent_tools.get_catalyst_snapshot",
        lambda ticker, lookback_days=7: {
            "ok": True,
            "ticker": ticker,
            "source": "fmp",
            "timestamp": "x",
            "data": {
                "news_snapshot": {"ok": True},
                "earnings_snapshot": {"ok": True},
                "catalyst_score": {"catalyst_score": 65.0, "catalyst_label": "positive"},
            },
            "error": None,
        },
    )

    result = get_catalyst_brain_tool("AAPL")

    assert result["ok"] is True
    assert result["tool"] == "get_catalyst_brain_tool"
    assert result["data"]["catalyst_score"]["catalyst_label"] == "positive"


def test_get_market_regime_tool_returns_standard_envelope(monkeypatch):
    monkeypatch.setattr(
        "tools.agent_tools.get_market_regime_snapshot",
        lambda include_breadth=False, db_path="strategy_library.db": {
            "ok": True,
            "regime": "risk_on_uptrend",
            "confidence_label": "high",
            "trade_aggressiveness": "normal",
            "max_trades_adjustment": 1,
            "long_bias": True,
            "short_bias": False,
            "options_aggressiveness": "normal",
            "index_context": {},
            "breadth_context": {},
            "risk_flags": [],
            "summary": "Risk on.",
        },
    )

    result = get_market_regime_tool(include_breadth=True)

    assert result["ok"] is True
    assert result["tool"] == "get_market_regime_tool"
    assert result["data"]["regime"] == "risk_on_uptrend"


def test_get_relative_strength_tool_returns_standard_envelope(monkeypatch):
    monkeypatch.setattr(
        "tools.agent_tools.get_relative_strength_snapshot",
        lambda ticker, sector=None, include_sector=True, db_path="strategy_library.db": {
            "ok": True,
            "ticker": ticker,
            "sector": sector,
            "relative_strength_label": "outperforming",
            "relative_strength_score": 74.0,
            "risk_flags": [],
            "summary": "Outperforming.",
        },
    )

    result = get_relative_strength_tool("AAPL", sector="Technology", include_sector=True)

    assert result["ok"] is True
    assert result["tool"] == "get_relative_strength_tool"
    assert result["data"]["relative_strength_label"] == "outperforming"


def test_get_deep_research_brief_tool_returns_standard_envelope(monkeypatch):
    monkeypatch.setattr(
        "tools.agent_tools.build_research_brief",
        lambda **kwargs: {
            "ok": True,
            "timestamp": "2026-06-07T00:00:00+00:00",
            "ticker": kwargs["ticker"],
            "brief_type": "deep_research",
            "research_summary": "AAPL research brief.",
            "trade_thesis": {"thesis": "AAPL has a valid setup."},
            "bull_case": {"points": ["Passed constraints."]},
            "bear_case": {"points": ["No near-term catalyst."]},
            "key_risks": ["Risk flag"],
            "evidence_table": [{"category": "technical", "source": "system"}],
            "research_conviction": {"score": 72.0, "label": "medium"},
            "data_quality": {"missing_sections": [], "stale_data_flags": []},
            "raw_context": {},
            "error": None,
        },
    )

    result = get_deep_research_brief_tool("AAPL", include_options=True)

    assert result["ok"] is True
    assert result["tool"] == "get_deep_research_brief_tool"
    assert result["data"]["ticker"] == "AAPL"
    assert result["data"]["brief_type"] == "deep_research"


def test_get_sec_filing_brain_tool_returns_standard_envelope(monkeypatch):
    monkeypatch.setattr(
        "tools.agent_tools.get_sec_filing_snapshot",
        lambda ticker, lookback_days=120: {
            "ok": True,
            "ticker": ticker,
            "source": "mock",
            "timestamp": "2026-06-07T00:00:00+00:00",
            "data": {
                "filing_analysis": {
                    "filing_risk_label": "medium",
                    "filing_risk_score": 48.0,
                }
            },
            "error": None,
        },
    )

    result = get_sec_filing_brain_tool("AAPL", lookback_days=90)

    assert result["ok"] is True
    assert result["tool"] == "get_sec_filing_brain_tool"
    assert result["data"]["ticker"] == "AAPL"


def test_get_earnings_transcript_brain_tool_returns_standard_envelope(monkeypatch):
    monkeypatch.setattr(
        "tools.agent_tools.get_earnings_transcript_snapshot",
        lambda ticker, lookback_quarters=2: {
            "ok": True,
            "ticker": ticker,
            "source": "mock",
            "timestamp": "2026-06-07T00:00:00+00:00",
            "data": {
                "earnings_quality": {
                    "earnings_quality_label": "strong",
                    "earnings_quality_score": 72.0,
                }
            },
            "error": None,
        },
    )

    result = get_earnings_transcript_brain_tool("AAPL", lookback_quarters=1)

    assert result["ok"] is True
    assert result["tool"] == "get_earnings_transcript_brain_tool"
    assert result["data"]["ticker"] == "AAPL"


def test_run_trading_brain_tool_routes_all_modes(monkeypatch):
    monkeypatch.setattr("tools.agent_tools.run_weekly_trade_hunt", lambda **kwargs: {"ok": True, "mode": "weekly_trade_hunt"})
    monkeypatch.setattr("tools.agent_tools.review_ticker_opportunity", lambda **kwargs: {"ok": True, "mode": "review_ticker"})
    monkeypatch.setattr("tools.agent_tools.monitor_open_trades", lambda **kwargs: {"ok": True, "mode": "monitor_open_trades"})

    weekly = run_trading_brain_tool(mode="weekly_trade_hunt")
    review = run_trading_brain_tool(mode="review_ticker", ticker="AAPL")
    monitor = run_trading_brain_tool(mode="monitor_open_trades")
    invalid = run_trading_brain_tool(mode="unknown_mode")

    assert weekly["ok"] is True
    assert weekly["data"]["mode"] == "weekly_trade_hunt"
    assert review["ok"] is True
    assert review["data"]["mode"] == "review_ticker"
    assert monitor["ok"] is True
    assert monitor["data"]["mode"] == "monitor_open_trades"
    assert invalid["ok"] is False


def test_run_trading_brain_tool_passes_option_flags(monkeypatch):
    captured = {}

    def fake_run_weekly_trade_hunt(**kwargs):
        captured.update(kwargs)
        return {"ok": True, "mode": "weekly_trade_hunt"}

    monkeypatch.setattr("tools.agent_tools.run_weekly_trade_hunt", fake_run_weekly_trade_hunt)

    result = run_trading_brain_tool(
        mode="weekly_trade_hunt",
        include_market_regime=False,
        include_relative_strength=False,
        include_research_briefs=True,
        include_options=True,
        prefer_options=True,
        max_option_contracts_per_trade=2,
    )

    assert result["ok"] is True
    assert captured["include_market_regime"] is False
    assert captured["include_relative_strength"] is False
    assert captured["include_research_briefs"] is True
    assert captured["include_options"] is True
    assert captured["prefer_options"] is True
    assert captured["max_option_contracts_per_trade"] == 2


def test_run_trading_brain_tool_review_mode_passes_include_research_brief(monkeypatch):
    captured = {}

    def fake_review_ticker_opportunity(**kwargs):
        captured.update(kwargs)
        return {"ok": True, "mode": "review_ticker"}

    monkeypatch.setattr("tools.agent_tools.review_ticker_opportunity", fake_review_ticker_opportunity)

    result = run_trading_brain_tool(
        mode="review_ticker",
        ticker="AAPL",
        include_research_brief=False,
        include_sec_filings=False,
        include_earnings_transcripts=False,
    )

    assert result["ok"] is True
    assert captured["ticker"] == "AAPL"
    assert captured["include_research_brief"] is False
    assert captured["include_sec_filings"] is False
    assert captured["include_earnings_transcripts"] is False


def test_run_paper_trading_tool_routes_actions(monkeypatch):
    captured = {}

    def fake_run_paper_trade_cycle(**kwargs):
        captured.update(kwargs)
        return {"ok": True, "mode": "paper_trading", "summary": {"message": "cycle"}}

    monkeypatch.setattr("tools.agent_tools.run_paper_trade_cycle", fake_run_paper_trade_cycle)
    monkeypatch.setattr("tools.agent_tools.review_paper_portfolio", lambda **kwargs: captured.update({"review_kwargs": kwargs}) or {"ok": True, "mode": "paper_trading", "summary": {"message": "review"}})
    monkeypatch.setattr("tools.agent_tools.get_paper_trading_summary", lambda **kwargs: {"ok": True, "mode": "paper_trading", "warning": "simulated"})

    cycle = run_paper_trading_tool(action="cycle", include_market_regime=False, include_relative_strength=False, include_options=True, prefer_options=True, max_option_contracts_per_trade=2)
    review = run_paper_trading_tool(action="review", include_trade_reviews=False, store_review_memory=True)
    summary = run_paper_trading_tool(action="summary")
    invalid = run_paper_trading_tool(action="bad_action")

    assert cycle["ok"] is True
    assert cycle["tool"] == "run_paper_trading_tool"
    assert captured["include_market_regime"] is False
    assert captured["include_relative_strength"] is False
    assert captured["include_options"] is True
    assert captured["prefer_options"] is True
    assert captured["max_option_contracts_per_trade"] == 2
    assert review["ok"] is True
    assert summary["ok"] is True
    assert summary["data"]["mode"] == "paper_trading"
    assert captured["review_kwargs"]["include_trade_reviews"] is False
    assert captured["review_kwargs"]["store_review_memory"] is True
    assert invalid["ok"] is False


def test_scan_options_for_candidate_tool_returns_structured_output(monkeypatch):
    monkeypatch.setattr(
        "tools.agent_tools.scan_options_for_stock_candidate",
        lambda candidate, max_contracts=5: {
            "ok": True,
            "ticker": candidate["ticker"],
            "underlying_candidate": candidate,
            "best_option_candidates": [{"option_contract": "AAPLC125"}],
            "rejected_option_candidates": [{"option_contract": "AAPLC130"}],
            "summary": {"contracts_evaluated": 2, "contracts_passed": 1, "message": "ok"},
            "errors": [],
        },
    )

    result = scan_options_for_candidate_tool({"ticker": "AAPL", "direction": "long"}, max_contracts=3)

    assert result["ok"] is True
    assert result["tool"] == "scan_options_for_candidate_tool"
    assert result["data"]["best_option_candidates"][0]["option_contract"] == "AAPLC125"
