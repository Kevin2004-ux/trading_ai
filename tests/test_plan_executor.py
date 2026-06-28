from copy import deepcopy

from agent.trading_brain import run_weekly_trade_hunt
from planning import build_combined_universe, build_default_scan_plan, execute_scan_plan


def _stock(
    ticker,
    status="watchlist",
    score=80,
    relative_volume=1.3,
    risk_reward=2.4,
    technical_status="confirmed",
    rs_label="outperforming",
    failed_constraints=None,
):
    feature_provenance = {
        "current_price": {
            "feature_name": "current_price",
            "feature_value_available": True,
            "provider": "test_market_data",
            "provider_type": "market_data",
            "source": "quote.last_price",
            "allowed_for_recommendation": True,
            "allowed_for_research_only": True,
            "warnings": [],
            "errors": [],
        },
        "sma_20": {
            "feature_name": "sma_20",
            "feature_value_available": True,
            "provider": "test_market_data",
            "provider_type": "market_data",
            "source": "technical_snapshot",
            "allowed_for_recommendation": True,
            "allowed_for_research_only": True,
            "warnings": [],
            "errors": [],
        },
    }
    return {
        "ticker": ticker,
        "asset_type": "stock",
        "direction": "long",
        "setup_type": "momentum_pullback",
        "recommendation_status": status,
        "passed": status in {"recommendable", "watchlist"},
        "current_price": 100.0,
        "entry_price": 101.0,
        "target_price": 115.0,
        "stop_loss": 95.0,
        "risk_reward": risk_reward,
        "score": score,
        "sma_20": 98.0,
        "sma_50": 94.0,
        "average_volume_20": 2_000_000,
        "relative_volume": relative_volume,
        "atr_percent": 0.04,
        "data_quality": {"ok": True, "quality_label": "good", "errors": [], "warnings": []},
        "feature_provenance": feature_provenance,
        "feature_provenance_summary": {
            "feature_count": 2,
            "available_count": 2,
            "allowed_for_recommendation_count": 2,
            "unsafe_features": [],
            "providers": ["test_market_data"],
            "warnings": [],
            "errors": [],
        },
        "data_freshness": {"ok": True, "freshness_label": "fresh"},
        "technical_confirmation_summary": {
            "status": technical_status,
            "score_adjustment": 5 if technical_status == "confirmed" else -5,
            "warnings": [] if technical_status == "confirmed" else ["Technical confirmation is weak."],
            "reasons": ["Technical confirmation constructive."] if technical_status == "confirmed" else [],
        },
        "relative_strength_context": {"relative_strength_label": rs_label},
        "why_this_profile_matched": [f"{ticker} matched deterministic profile."],
        "failed_constraints": failed_constraints or [],
        "rejection_reason": "; ".join(failed_constraints or []),
    }


def _provider_failure(ticker="AAPL"):
    reason = "IBKR historical bars unavailable: [Errno 61] Connect call failed ('127.0.0.1', 7496)"
    return {
        "ticker": ticker,
        "asset_type": "stock",
        "recommendation_status": "rejected",
        "current_price": None,
        "entry_price": None,
        "target_price": None,
        "stop_loss": None,
        "score": 0,
        "technical_snapshot": {},
        "failed_constraints": ["scanner_error"],
        "rejection_reason": reason,
        "data_quality": {"ok": False, "quality_label": "unavailable", "errors": [reason], "warnings": []},
    }


def _fake_trading_result():
    return {
        "ok": True,
        "mode": "weekly_trade_hunt",
        "universe_result": {"ok": True, "tickers": ["NVDA", "MSFT", "TSLA"], "count": 3},
        "scan_result": {
            "ok": True,
            "profiles_run": ["momentum_breakout"],
            "watchlist_candidates": [_stock("MSFT", status="watchlist", score=82)],
            "rejected_candidates": [
                _stock("TSLA", status="rejected", score=72, relative_volume=1.05, failed_constraints=["minimum_relative_volume"]),
            ],
            "scan_execution_summary": {"partial_results_used": False},
        },
        "selection_result": {
            "ok": True,
            "selected_trades": [],
            "watchlist_alternatives": [_stock("MSFT", status="watchlist", score=82)],
            "rejected_candidates": [_stock("TSLA", status="rejected", score=72, relative_volume=1.05, failed_constraints=["minimum_relative_volume"])],
        },
        "decision_result": {
            "ok": True,
            "final_recommendations": [_stock("NVDA", status="recommendable", score=94, risk_reward=3.1)],
            "logged_recommendations": [],
            "not_selected": [],
        },
        "summary": {"profiles_run": ["momentum_breakout"], "selected_count": 1, "logged_count": 0},
        "errors": [],
    }


def test_combined_multi_universe_order_dedupes_and_enforces_max():
    result = build_combined_universe(
        {
            "universes": ["large_cap", "active", "tech"],
            "custom_tickers": [],
            "max_tickers": 45,
        }
    )

    assert result["ok"] is True
    assert result["universes_loaded"] == ["large_cap", "active", "tech"]
    assert result["tickers"][:5] == ["AAPL", "MSFT", "NVDA", "AMZN", "GOOGL"]
    assert len(result["tickers"]) == len(set(result["tickers"]))
    assert result["count"] == 45
    assert result["tickers"] != ["AAPL", "MSFT", "NVDA", "AMZN", "GOOGL"][: result["count"]]


def test_run_weekly_trade_hunt_signature_keeps_backward_compatible_optional_params():
    import inspect

    signature = inspect.signature(run_weekly_trade_hunt)

    assert signature.parameters["tickers"].default is None
    assert signature.parameters["universe_result_override"].default is None
    assert signature.parameters["max_total_candidates"].default is None
    assert signature.parameters["scanner_config"].default is None


def test_stock_only_execution_passes_no_options_and_auto_log_false(monkeypatch):
    captured = {}

    def fake_run_weekly_trade_hunt(**kwargs):
        captured.update(kwargs)
        return _fake_trading_result()

    monkeypatch.setattr("planning.plan_executor.run_weekly_trade_hunt", fake_run_weekly_trade_hunt)

    result = execute_scan_plan(
        {
            "requested_instrument": "stocks",
            "universes": ["large_cap", "active"],
            "max_tickers": 10,
            "include_options": True,
            "prefer_options": True,
        }
    )

    assert result["ok"] is True
    assert captured["include_options"] is False
    assert captured["prefer_options"] is False
    assert captured["auto_log"] is False
    assert result["execution_summary"]["include_options"] is False
    assert result["assistant_response"]["top_options"] == []
    assert result["option_discovery"]["status"] == "disabled"


def test_broad_plan_with_dynamic_discovery_uses_discovered_tickers(monkeypatch):
    captured = {}

    def fake_discover_candidates(**kwargs):
        captured["discovery_kwargs"] = kwargs
        return {
            "ok": True,
            "discovery_version": "candidate_discovery_v1",
            "discovered_at": "2026-06-28T12:00:00+00:00",
            "as_of": "2026-06-28T12:00:00+00:00",
            "requested_sources": kwargs.get("requested_sources", []),
            "sources_used": ["manual_hotlist"],
            "candidates": [
                {"ticker": "MSFT", "source_type": "manual_hotlist", "discovery_score": 98, "reasons": ["Manual hotlist."], "requires_live_validation": True, "point_in_time_safe": True},
                {"ticker": "NVDA", "source_type": "manual_hotlist", "discovery_score": 97, "reasons": ["Manual hotlist."], "requires_live_validation": True, "point_in_time_safe": True},
            ],
            "tickers": ["MSFT", "NVDA"],
            "discovered_count": 2,
            "warnings": [],
            "errors": [],
            "point_in_time_safe": True,
            "requires_live_validation": True,
        }

    def fake_run_weekly_trade_hunt(**kwargs):
        captured["run_kwargs"] = kwargs
        return _fake_trading_result()

    monkeypatch.setattr("planning.plan_executor.discover_candidates", fake_discover_candidates)
    monkeypatch.setattr("planning.plan_executor.run_weekly_trade_hunt", fake_run_weekly_trade_hunt)

    result = execute_scan_plan(
        {"requested_instrument": "stocks", "objective": "best_ideas", "universes": ["large_cap"], "max_tickers": 10},
        internal_controls={
            "use_dynamic_discovery": True,
            "max_discovered_tickers": 2,
            "discovery_sources": ["manual_hotlist"],
        },
    )

    assert result["ok"] is True
    assert captured["discovery_kwargs"]["max_tickers"] == 2
    assert captured["run_kwargs"]["tickers"] == ["MSFT", "NVDA"]
    assert captured["run_kwargs"]["auto_log"] is False
    assert result["paper_trading_only"] is True
    assert result["brokerage_execution_enabled"] is False
    assert result["universe_result"]["source"] == "dynamic_discovery"
    assert result["discovery_result"]["discovered_count"] == 2
    assert result["discovery_summary"]["discovery_used"] is True
    assert result["discovery_summary"]["discovered_count"] == 2
    assert result["discovery_summary"]["sources_used"] == ["manual_hotlist"]
    assert result["discovery_summary"]["top_candidates"][0]["ticker"] == "MSFT"
    assert result["assistant_response"]["market_state"]["discovery_used"] is True
    assert result["assistant_response"]["market_state"]["discovered_count"] == 2
    assert result["execution_summary"]["ticker_count_executed"] == 2
    assert result["execution_summary"]["discovery_used"] is True
    assert result["execution_summary"]["discovery_summary"]["discovery_used"] is True
    assert result["execution_summary"]["provider_capabilities"]
    assert result["assistant_response"]["market_state"]["provider_capabilities"]
    assert result["assistant_response"]["market_state"]["provider_capabilities"][0]["provider_name"] == "test_market_data"


def test_custom_ticker_plan_bypasses_dynamic_discovery(monkeypatch):
    captured = {"discover_called": False}

    def fake_discover_candidates(**kwargs):
        captured["discover_called"] = True
        return {"ok": True, "tickers": ["MSFT"], "discovered_count": 1, "warnings": [], "errors": []}

    def fake_run_weekly_trade_hunt(**kwargs):
        captured["run_kwargs"] = kwargs
        return _fake_trading_result()

    monkeypatch.setattr("planning.plan_executor.discover_candidates", fake_discover_candidates)
    monkeypatch.setattr("planning.plan_executor.run_weekly_trade_hunt", fake_run_weekly_trade_hunt)

    result = execute_scan_plan(
        {
            "requested_instrument": "stocks",
            "objective": "ticker_review",
            "universes": ["custom"],
            "custom_tickers": ["AAPL"],
            "max_tickers": 1,
        },
        internal_controls={"use_dynamic_discovery": True, "max_discovered_tickers": 5},
    )

    assert captured["discover_called"] is False
    assert captured["run_kwargs"]["tickers"] == ["AAPL"]
    assert result["universe_result"]["source"] == "scan_plan_combined"
    assert result["execution_summary"]["ticker_count_executed"] == 1
    assert result["discovery_summary"]["discovery_used"] is False
    assert result["discovery_summary"]["bypass_reason"] == "explicit_ticker_scope"
    assert result["assistant_response"]["market_state"]["discovery_summary"]["bypass_reason"] == "explicit_ticker_scope"


def test_explicit_ticker_review_reports_bypass_even_without_discovery_controls(monkeypatch):
    monkeypatch.setattr("planning.plan_executor.run_weekly_trade_hunt", lambda **kwargs: _fake_trading_result())

    result = execute_scan_plan(
        {
            "requested_instrument": "stocks",
            "objective": "ticker_review",
            "universes": ["custom"],
            "custom_tickers": ["AAPL"],
            "max_tickers": 1,
        }
    )

    assert result["discovery_summary"]["discovery_used"] is False
    assert result["discovery_summary"]["bypass_reason"] == "explicit_ticker_scope"
    assert result["assistant_response"]["market_state"]["discovery_summary"]["bypass_reason"] == "explicit_ticker_scope"


def test_empty_dynamic_discovery_falls_back_to_combined_universe(monkeypatch):
    captured = {}

    def fake_discover_candidates(**kwargs):
        return {
            "ok": True,
            "discovery_version": "candidate_discovery_v1",
            "discovered_at": "2026-06-28T12:00:00+00:00",
            "as_of": "2026-06-28T12:00:00+00:00",
            "requested_sources": kwargs.get("requested_sources", []),
            "sources_used": [],
            "candidates": [],
            "tickers": [],
            "discovered_count": 0,
            "warnings": ["No discovery candidates available."],
            "errors": [],
            "point_in_time_safe": True,
            "requires_live_validation": True,
        }

    def fake_run_weekly_trade_hunt(**kwargs):
        captured["run_kwargs"] = kwargs
        return _fake_trading_result()

    monkeypatch.setattr("planning.plan_executor.discover_candidates", fake_discover_candidates)
    monkeypatch.setattr("planning.plan_executor.run_weekly_trade_hunt", fake_run_weekly_trade_hunt)

    result = execute_scan_plan(
        {"requested_instrument": "stocks", "objective": "best_ideas", "universes": ["large_cap"], "max_tickers": 3},
        internal_controls={"use_dynamic_discovery": True, "max_discovered_tickers": 3},
    )

    assert captured["run_kwargs"]["tickers"] == ["AAPL", "MSFT", "NVDA"]
    assert result["universe_result"]["source"] == "scan_plan_combined"
    assert result["discovery_result"]["discovered_count"] == 0
    assert result["discovery_summary"]["fallback_used"] is True
    assert result["discovery_summary"]["discovery_used"] is False
    assert result["execution_summary"]["discovery_summary"]["fallback_used"] is True
    assert any("falling back" in warning.lower() for warning in result["warnings"])
    assert result["execution_summary"]["auto_log"] is False


def test_discovery_score_does_not_replace_final_candidate_scores(monkeypatch):
    def fake_discover_candidates(**kwargs):
        return {
            "ok": True,
            "discovery_version": "candidate_discovery_v1",
            "discovered_at": "2026-06-28T12:00:00+00:00",
            "as_of": "2026-06-28T12:00:00+00:00",
            "requested_sources": ["manual_hotlist"],
            "sources_used": ["manual_hotlist"],
            "candidates": [
                {"ticker": "MSFT", "source_type": "manual_hotlist", "discovery_score": 99, "requires_live_validation": True},
            ],
            "tickers": ["MSFT"],
            "discovered_count": 1,
            "warnings": [],
            "errors": [],
            "point_in_time_safe": True,
            "requires_live_validation": True,
        }

    def fake_run_weekly_trade_hunt(**kwargs):
        result = _fake_trading_result()
        result["decision_result"]["final_recommendations"] = []
        result["selection_result"]["watchlist_alternatives"] = [_stock("MSFT", status="watchlist", score=42)]
        result["selection_result"]["rejected_candidates"] = []
        result["scan_result"]["watchlist_candidates"] = [_stock("MSFT", status="watchlist", score=42)]
        result["scan_result"]["rejected_candidates"] = []
        return result

    monkeypatch.setattr("planning.plan_executor.discover_candidates", fake_discover_candidates)
    monkeypatch.setattr("planning.plan_executor.run_weekly_trade_hunt", fake_run_weekly_trade_hunt)

    result = execute_scan_plan(
        {"requested_instrument": "stocks", "objective": "best_ideas", "universes": ["large_cap"], "max_tickers": 5},
        internal_controls={"use_dynamic_discovery": True, "max_discovered_tickers": 1},
    )

    top_stock = result["assistant_response"]["top_stocks"][0]
    assert result["discovery_summary"]["top_candidates"][0]["discovery_score"] == 99
    assert top_stock["engine_score"] == 42
    assert top_stock["opportunity_score"] != 99
    assert top_stock["status"] == "watchlist"
    assert top_stock["rank"] == 1


def test_options_execution_not_ready_keeps_final_option_eligibility_false(monkeypatch):
    captured = {}

    def fake_run_weekly_trade_hunt(**kwargs):
        captured.update(kwargs)
        return _fake_trading_result()

    monkeypatch.setattr("planning.plan_executor.run_weekly_trade_hunt", fake_run_weekly_trade_hunt)
    monkeypatch.setattr(
        "planning.plan_executor.discover_option_ideas",
        lambda *args, **kwargs: {
            "ok": True,
            "discovery_version": "option_discovery_v1",
            "status": "partial",
            "paper_trading_only": True,
            "brokerage_execution_enabled": False,
            "requested": True,
            "provider_status": "degraded",
            "options_final_eligibility": False,
            "underlyings_considered": [],
            "underlying_shortlist": [],
            "contracts_evaluated": 0,
            "strategies_evaluated": 0,
            "paper_eligible_contracts": [],
            "research_only_contracts": [],
            "blocked_contracts": [],
            "underlying_watchlist": [{"ticker": "NVDA", "underlying_opportunity_score": 90, "required_before_contract_ranking": ["bid/ask"]}],
            "missing_requirements": ["bid/ask"],
            "warnings": [],
            "errors": [],
        },
    )

    result = execute_scan_plan(
        {"requested_instrument": "options", "include_options": False, "prefer_options": True, "max_tickers": 5},
        runtime_context={"safe_to_run_options": False},
    )

    assert captured["include_options"] is True
    assert result["execution_config"]["options_final_eligibility"] is False
    assert result["execution_summary"]["options_final_eligibility"] is False
    assert result["option_discovery"]["status"] == "partial"
    assert result["assistant_response"]["option_underlying_watchlist"]
    assert any("final option recommendations remain blocked" in warning for warning in result["warnings"])


def test_option_discovery_uses_ranked_underlying_near_misses_not_only_final_selected(monkeypatch):
    captured = {}

    def fake_run_weekly_trade_hunt(**kwargs):
        result = _fake_trading_result()
        result["decision_result"]["final_recommendations"] = []
        result["selection_result"]["selected_trades"] = []
        return result

    def fake_discover(stock_candidates, **kwargs):
        captured["stock_candidates"] = stock_candidates
        captured["kwargs"] = kwargs
        return {
            "ok": True,
            "discovery_version": "option_discovery_v1",
            "status": "available",
            "paper_trading_only": True,
            "brokerage_execution_enabled": False,
            "requested": True,
            "provider_status": "available",
            "options_final_eligibility": False,
            "underlyings_considered": [],
            "underlying_shortlist": [{"ticker": "MSFT"}],
            "contracts_evaluated": 1,
            "strategies_evaluated": 1,
            "paper_eligible_contracts": [],
            "research_only_contracts": [
                {
                    "ticker": "MSFT",
                    "underlying_ticker": "MSFT",
                    "asset_type": "option",
                    "recommendation_status": "research_only",
                    "strategy": "long_call",
                    "option_contract": "MSFT260717C00100000",
                    "option_type": "call",
                    "strike": 100,
                    "expiration": "2026-07-17",
                    "days_to_expiration": 25,
                    "bid": 3.8,
                    "ask": 4.0,
                    "mid": 3.9,
                    "option_opportunity_score": 74,
                }
            ],
            "blocked_contracts": [],
            "underlying_watchlist": [],
            "missing_requirements": [],
            "warnings": [],
            "errors": [],
        }

    monkeypatch.setattr("planning.plan_executor.run_weekly_trade_hunt", fake_run_weekly_trade_hunt)
    monkeypatch.setattr("planning.plan_executor.discover_option_ideas", fake_discover)

    result = execute_scan_plan({"requested_instrument": "options", "include_options": True, "max_tickers": 3})

    tickers = {row["ticker"] for row in captured["stock_candidates"]}
    assert {"MSFT", "TSLA"}.issubset(tickers)
    assert result["option_discovery"]["status"] == "available"
    assert result["assistant_response"]["top_options"][0]["option_contract"] == "MSFT260717C00100000"
    assert result["trading_result"]["decision_result"]["final_recommendations"] == []


def test_option_premium_intent_reaches_option_preferences(monkeypatch):
    captured = {}

    def fake_run_weekly_trade_hunt(**kwargs):
        return _fake_trading_result()

    def fake_discover(stock_candidates, **kwargs):
        captured["option_preferences"] = kwargs.get("option_preferences")
        return {
            "ok": True,
            "discovery_version": "option_discovery_v1",
            "status": "unavailable",
            "paper_trading_only": True,
            "brokerage_execution_enabled": False,
            "requested": True,
            "provider_status": "unknown",
            "options_final_eligibility": False,
            "underlyings_considered": [],
            "underlying_shortlist": [],
            "contracts_evaluated": 0,
            "strategies_evaluated": 0,
            "paper_eligible_contracts": [],
            "research_only_contracts": [],
            "blocked_contracts": [],
            "underlying_watchlist": [],
            "missing_requirements": [],
            "warnings": [],
            "errors": [],
        }

    monkeypatch.setattr("planning.plan_executor.run_weekly_trade_hunt", fake_run_weekly_trade_hunt)
    monkeypatch.setattr("planning.plan_executor.discover_option_ideas", fake_discover)

    result = execute_scan_plan(
        {
            "requested_instrument": "options",
            "include_options": True,
            "option_preferences": {"max_option_premium": 250, "min_dte": 14, "max_dte": 45},
        },
        internal_controls={
            "intent_constraints": {
                "requested_instrument": "options",
                "max_option_premium": 250,
                "require_upcoming_earnings": True,
            }
        },
    )

    assert result["ok"] is True
    assert captured["option_preferences"]["max_option_premium"] == 250
    assert result["execution_config"]["max_option_premium"] == 250
    assert result["user_intent"]["max_option_premium"] == 250
    assert result["paper_trading_only"] is True
    assert result["brokerage_execution_enabled"] is False


def test_provider_unavailable_returns_unavailable_and_empty_rankings(monkeypatch):
    def fake_run_weekly_trade_hunt(**kwargs):
        return {
            "ok": True,
            "scan_result": {"rejected_candidates": [_provider_failure("AAPL"), _provider_failure("MSFT")]},
            "selection_result": {"watchlist_alternatives": [], "rejected_candidates": []},
            "decision_result": {"final_recommendations": [], "logged_recommendations": []},
            "summary": {"profiles_run": kwargs.get("profiles", []), "logged_count": 0},
            "errors": [],
        }

    monkeypatch.setattr("planning.plan_executor.run_weekly_trade_hunt", fake_run_weekly_trade_hunt)

    result = execute_scan_plan({"requested_instrument": "stocks", "universes": ["large_cap"], "max_tickers": 2})

    assert result["execution_summary"]["status"] == "unavailable"
    assert result["best_available_ideas"]["ranking_status"] == "unavailable"
    assert result["assistant_response"]["top_stocks"] == []
    assert result["assistant_response"]["top_options"] == []
    assert sum("IBKR/TWS is not reachable" in item for item in result["best_available_ideas"]["system_issues"]) == 1
    assert result["trading_result"]["decision_result"]["logged_recommendations"] == []


def test_legitimate_results_preserve_statuses_and_return_opportunity_ranking(monkeypatch):
    monkeypatch.setattr("planning.plan_executor.run_weekly_trade_hunt", lambda **kwargs: _fake_trading_result())

    result = execute_scan_plan({"requested_instrument": "stocks", "universes": ["large_cap"], "max_tickers": 3})
    statuses = [row["status"] for row in result["assistant_response"]["top_stocks"]]

    assert result["execution_summary"]["status"] == "completed"
    assert "paper_eligible" in statuses
    assert "watchlist" in statuses
    assert "blocked" in statuses
    assert result["assistant_response"]["top_stocks"][0]["opportunity_score"] is not None


def test_opportunity_weights_affect_research_order_without_status_changes(monkeypatch):
    def fake_run_weekly_trade_hunt(**kwargs):
        high_engine = _stock("AAA", status="rejected", score=100, technical_status="warning", rs_label="underperforming", failed_constraints=["technical_confirmation_rejected"])
        strong_structure = _stock("BBB", status="rejected", score=40, technical_status="confirmed", rs_label="market_leader", failed_constraints=["minimum_score_to_recommend"])
        result = _fake_trading_result()
        result["decision_result"]["final_recommendations"] = []
        result["selection_result"]["watchlist_alternatives"] = []
        result["selection_result"]["rejected_candidates"] = [high_engine, strong_structure]
        result["scan_result"]["watchlist_candidates"] = []
        result["scan_result"]["rejected_candidates"] = [high_engine, strong_structure]
        return result

    monkeypatch.setattr("planning.plan_executor.run_weekly_trade_hunt", fake_run_weekly_trade_hunt)

    baseline = execute_scan_plan({"requested_instrument": "stocks", "universes": ["large_cap"], "max_tickers": 3})
    weighted = execute_scan_plan(
        {
            "requested_instrument": "stocks",
            "universes": ["large_cap"],
            "max_tickers": 3,
            "soft_adjustments": {
                "opportunity_weights": {
                    "engine_core": 0,
                    "technical_confirmation": 10,
                    "relative_strength": 10,
                }
            },
        }
    )

    assert baseline["assistant_response"]["top_stocks"][0]["ticker"] == "AAA"
    assert weighted["assistant_response"]["top_stocks"][0]["ticker"] == "BBB"
    assert all(row["status"] == "blocked" for row in weighted["assistant_response"]["top_stocks"])


def test_unapplied_profile_and_soft_preferences_are_reported(monkeypatch):
    monkeypatch.setattr("planning.plan_executor.run_weekly_trade_hunt", lambda **kwargs: _fake_trading_result())

    result = execute_scan_plan(
        {
            "requested_instrument": "stocks",
            "universes": ["large_cap"],
            "profiles": ["bad_profile", "momentum_breakout"],
            "soft_adjustments": {
                "profile_weights": {"momentum_breakout": 1},
                "minimum_relative_volume": 1.5,
                "breakout_proximity_percent": 0.02,
            },
        }
    )

    unapplied = result["execution_summary"]["unapplied_preferences"]
    assert any(item["field"] == "profile_weights" for item in unapplied)
    assert any(item["field"] == "minimum_relative_volume" for item in unapplied)
    assert result["approved_plan"]["profiles"] == ["momentum_breakout"]


def test_execute_route_and_chat_do_not_log_or_autolog(monkeypatch):
    captured = {"calls": []}

    def fake_run_weekly_trade_hunt(**kwargs):
        captured["calls"].append(kwargs)
        return _fake_trading_result()

    monkeypatch.setattr("planning.plan_executor.run_weekly_trade_hunt", fake_run_weekly_trade_hunt)

    result = execute_scan_plan({"requested_instrument": "stocks", "universes": ["large_cap"], "max_tickers": 3})

    assert result["trading_result"]["decision_result"]["logged_recommendations"] == []
    assert captured["calls"][0]["auto_log"] is False


def test_research_requested_runs_after_deterministic_ranking_and_preserves_order_status_score(monkeypatch):
    captured = {}
    monkeypatch.setattr("planning.plan_executor.run_weekly_trade_hunt", lambda **kwargs: _fake_trading_result())

    def fake_build_current_research(tickers, scopes=None, candidate_context=None, request_id=None, as_of=None, provider=None):
        captured["tickers"] = tickers
        captured["scopes"] = scopes
        captured["candidate_context"] = candidate_context
        return {
            "ok": True,
            "research_version": "current_research_v1",
            "status": "available",
            "provider": "local",
            "model": None,
            "request_id": request_id,
            "as_of": "2026-06-22T12:00:00Z",
            "web_search_used": False,
            "local_research_used": True,
            "cache_hit": False,
            "tickers_requested": tickers,
            "tickers_researched": tickers,
            "scopes_requested": scopes or [],
            "dossiers": [
                {
                    "ticker": tickers[0],
                    "status": "available",
                    "summary": "Current source-supported context.",
                    "evidence_items": [],
                    "positive_catalysts": ["Source-supported catalyst."],
                    "negative_catalysts": ["Source-supported risk."],
                    "neutral_context": [],
                    "uncertainties": [],
                    "conflicting_evidence": [],
                    "source_ids": ["source_1"],
                    "freshness": {"latest_source_date": "2026-06-22T12:00:00Z", "dated_source_count": 1, "undated_source_count": 0, "freshness_label": "current"},
                    "warnings": [],
                    "errors": [],
                }
            ],
            "sources": [{"source_id": "source_1", "url": "https://example.com/aapl", "title": "Example", "domain": "example.com", "published_at": "2026-06-22T12:00:00Z", "source_type": "news", "primary_source": False, "citation_start": None, "citation_end": None}],
            "warnings": [],
            "errors": [],
            "usage": {"input_tokens": None, "output_tokens": None, "total_tokens": None, "web_search_calls": 0, "extraction_calls": 0},
        }

    monkeypatch.setattr("planning.plan_executor.build_current_research", fake_build_current_research)

    result = execute_scan_plan(
        {
            "requested_instrument": "stocks",
            "universes": ["large_cap"],
            "max_tickers": 3,
            "research_preferences": {"include_news": True, "include_sec_filings": False, "include_earnings_transcripts": False},
        }
    )

    rows = result["assistant_response"]["top_stocks"]
    assert captured["tickers"] == [row["ticker"] for row in rows[:3]]
    assert captured["scopes"] == ["company_news"]
    assert [row["ticker"] for row in rows] == ["NVDA", "MSFT", "TSLA"]
    assert [row["status"] for row in rows] == ["paper_eligible", "watchlist", "blocked"]
    assert rows[0]["opportunity_score"] is not None
    assert rows[0]["research_status"] == "available"
    assert rows[0]["current_catalysts"] == ["Source-supported catalyst."]
    assert result["research"]["status"] == "available"


def test_research_not_requested_returns_disabled_shape(monkeypatch):
    monkeypatch.setattr("planning.plan_executor.run_weekly_trade_hunt", lambda **kwargs: _fake_trading_result())

    result = execute_scan_plan({"requested_instrument": "stocks", "universes": ["large_cap"], "max_tickers": 3})

    assert result["research"]["status"] == "disabled"
    assert result["research"]["dossiers"] == []
    assert all(row["research_status"] == "not_requested" for row in result["assistant_response"]["top_stocks"])
