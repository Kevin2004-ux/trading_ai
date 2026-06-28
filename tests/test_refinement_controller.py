import planning.refinement_controller as refinement
from planning import execute_adaptive_scan_plan, evaluate_scan_pass, plan_fingerprint


def _stock_row(ticker, status="watchlist", score=78, failed_constraints=None):
    bucket = "watchlist" if status == "watchlist" else "blocked_but_interesting"
    return {
        "ticker": ticker,
        "asset_type": "stock",
        "recommendation_status": status,
        "bucket": bucket,
        "score": score,
        "idea_score": score,
        "opportunity_score": score,
        "risk_reward": 2.2,
        "entry_price": 101.0,
        "target_price": 115.0,
        "stop_loss": 95.0,
        "failed_constraints": failed_constraints or [],
        "reason": "Deterministic near-miss with usable market data.",
        "data_quality": "good",
        "raw_candidate": {
            "ticker": ticker,
            "asset_type": "stock",
            "recommendation_status": status,
            "score": score,
            "current_price": 100.0,
            "entry_price": 101.0,
            "target_price": 115.0,
            "stop_loss": 95.0,
            "risk_reward": 2.2,
            "failed_constraints": failed_constraints or [],
            "data_quality": {"ok": True, "quality_label": "good", "errors": [], "warnings": []},
            "technical_snapshot": {"current_price": 100.0, "sma_20": 98.0, "relative_volume": 1.1},
        },
    }


def _execution_result(
    *,
    status="completed",
    ranking_status="available",
    paper=None,
    watchlist=None,
    blocked=None,
    system_issues=None,
    data_missing=None,
    partial=False,
):
    paper = paper or []
    watchlist = watchlist or []
    blocked = blocked or []
    system_issues = system_issues or []
    data_missing = data_missing or []
    top_stocks = paper + watchlist + blocked
    return {
        "ok": True,
        "execution_version": "scan_plan_executor_v1",
        "paper_trading_only": True,
        "brokerage_execution_enabled": False,
        "approved_plan": {"requested_instrument": "stocks", "include_options": False},
        "execution_config": {"include_options": False, "paper_trading_only": True, "brokerage_execution_enabled": False},
        "execution_summary": {"status": status, "partial_results": partial, "profiles_run": ["momentum_breakout"]},
        "trading_result": {"ok": True, "decision_result": {"logged_recommendations": []}, "errors": []},
        "best_available_ideas": {
            "ok": True,
            "ranking_status": ranking_status,
            "paper_eligible": paper,
            "stock_watchlist": watchlist,
            "option_research_only": [],
            "option_underlying_watchlist": [],
            "blocked_but_interesting": blocked,
            "why_no_final_trades": ["No final paper trades passed strict objective gates."],
            "data_missing": data_missing,
            "system_issues": system_issues,
            "next_steps": [],
            "warnings": [],
        },
        "assistant_response": {
            "ok": True,
            "response_type": "trade_ideas",
            "ranking_status": ranking_status,
            "market_state": {
                "provider_status": "unavailable" if ranking_status == "unavailable" else "available",
                "partial_results": partial,
            },
            "top_stocks": top_stocks,
            "top_options": [],
            "option_underlying_watchlist": [],
            "paper_eligible": paper,
            "research_only": watchlist,
            "blocked": blocked,
            "data_missing": data_missing,
            "system_issues": system_issues,
            "why_no_final_trades": ["No final paper trades passed strict objective gates."],
            "next_steps": [],
            "scan_summary": {"include_options": False, "partial_results": partial},
        },
        "formatted_response": "No final paper trades passed strict gates today.",
        "warnings": [],
        "errors": [],
    }


def test_evaluate_scan_pass_stops_when_provider_unavailable():
    result = _execution_result(
        ranking_status="unavailable",
        system_issues=["IBKR/TWS is not reachable on 127.0.0.1:7496."],
    )

    evaluation = evaluate_scan_pass(result, {"requested_instrument": "stocks", "objective": "best_ideas"}, pass_number=1)

    assert evaluation["evaluation_version"] == "scan_pass_evaluation_v1"
    assert evaluation["provider_status"] == "unavailable"
    assert evaluation["ranking_status"] == "unavailable"
    assert evaluation["refinement_allowed"] is False
    assert evaluation["recommended_action"] == "stop"


def test_execute_adaptive_scan_plan_stops_on_unavailable_provider(monkeypatch):
    monkeypatch.setattr(
        refinement,
        "execute_scan_plan",
        lambda *args, **kwargs: _execution_result(
            ranking_status="unavailable",
            data_missing=["Historical bars are unavailable from the configured market-data provider."],
            system_issues=["IBKR/TWS is not reachable on 127.0.0.1:7496."],
        ),
    )

    result = execute_adaptive_scan_plan(
        {"requested_instrument": "stocks", "universes": ["large_cap"], "max_tickers": 3, "refinement": {"max_passes": 3}},
        provider="deterministic",
    )

    assert result["ok"] is True
    assert result["status"] == "unavailable"
    assert result["passes_executed"] == 1
    assert result["refinement_used"] is False
    assert result["best_available_ideas"]["ranking_status"] == "unavailable"
    assert "Provider or essential market data unavailable" in result["stop_reason"]


def test_execute_adaptive_scan_plan_runs_bounded_second_pass_and_consolidates(monkeypatch):
    calls = []

    def fake_execute_scan_plan(plan, runtime_context=None, db_path="strategy_library.db", internal_controls=None):
        calls.append({"plan": dict(plan), "controls": dict(internal_controls or {})})
        universes = set(plan.get("universes") or [])
        if "growth" in universes:
            watchlist = [_stock_row("MSFT", score=82), _stock_row("NVDA", score=81), _stock_row("AMD", score=79)]
        else:
            watchlist = [_stock_row("AAPL", score=77)]
        return _execution_result(watchlist=watchlist)

    monkeypatch.setattr(refinement, "execute_scan_plan", fake_execute_scan_plan)
    monkeypatch.setattr(
        refinement,
        "discover_option_ideas",
        lambda *args, **kwargs: {
            "ok": True,
            "status": "disabled",
            "requested": False,
            "options_final_eligibility": False,
            "paper_eligible_contracts": [],
            "research_only_contracts": [],
            "blocked_contracts": [],
            "underlying_watchlist": [],
            "missing_requirements": [],
            "warnings": [],
            "errors": [],
        },
    )

    result = execute_adaptive_scan_plan(
        {"requested_instrument": "stocks", "universes": ["large_cap"], "max_tickers": 5, "max_candidates": 10, "refinement": {"max_passes": 2}},
        provider="deterministic",
    )

    assert result["status"] in {"completed", "completed_with_warnings"}
    assert result["passes_executed"] == 2
    assert result["refinement_used"] is True
    assert result["refinement_provider"] == "deterministic"
    assert result["passes"][0]["refinement_proposal"]["proposal"]["action"] == "refine"
    assert all(
        call["controls"] == {
            "run_current_research": False,
            "run_option_discovery": False,
            "record_learning": False,
        }
        for call in calls
    )
    assert result["assistant_response"]["refinement"]["used"] is True
    assert result["assistant_response"]["refinement"]["passes_executed"] == 2
    ranked = {row["ticker"] for row in result["best_available_ideas"]["stock_watchlist"]}
    assert {"MSFT", "NVDA", "AMD"}.issubset(ranked)


def test_adaptive_execution_stops_after_partial_legitimate_chat_pass(monkeypatch):
    calls = []

    def fake_execute_scan_plan(plan, runtime_context=None, db_path="strategy_library.db", internal_controls=None):
        calls.append({"plan": dict(plan), "controls": dict(internal_controls or {})})
        return _execution_result(
            watchlist=[_stock_row("AAPL", score=76)],
            partial=True,
            data_missing=["MSFT timed out before the total scan timeout."],
        )

    monkeypatch.setattr(refinement, "execute_scan_plan", fake_execute_scan_plan)

    result = execute_adaptive_scan_plan(
        {"requested_instrument": "stocks", "universes": ["large_cap"], "max_tickers": 7, "max_candidates": 6, "refinement": {"max_passes": 3}},
        provider="deterministic",
        internal_controls={"stop_after_first_legitimate_pass": True, "chat_broad_scan": True},
    )

    assert len(calls) == 1
    assert result["passes_executed"] == 1
    assert result["refinement_used"] is False
    assert "Legitimate ranked results found in the bounded first pass" in result["stop_reason"]
    assert result["best_available_ideas"]["ranking_status"] == "available"
    assert result["assistant_response"]["market_state"]["partial_results"] is True
    assert result["assistant_response"]["top_stocks"][0]["ticker"] == "AAPL"
    assert result["paper_trading_only"] is True
    assert result["brokerage_execution_enabled"] is False


def test_adaptive_execution_never_broadens_explicit_ticker_review(monkeypatch):
    calls = []
    monkeypatch.setattr(
        refinement,
        "execute_scan_plan",
        lambda plan, **kwargs: calls.append(dict(plan)) or _execution_result(watchlist=[_stock_row("AAPL", score=75)]),
    )

    result = execute_adaptive_scan_plan(
        {
            "objective": "ticker_review",
            "requested_instrument": "stocks",
            "universes": ["custom"],
            "custom_tickers": ["AAPL"],
            "max_tickers": 1,
            "refinement": {"max_passes": 3},
        },
        provider="deterministic",
    )

    assert result["max_passes"] == 1
    assert result["passes_executed"] == 1
    assert result["refinement_used"] is False
    assert calls[0]["custom_tickers"] == ["AAPL"]


def test_plan_fingerprint_includes_effective_ticker_set():
    plan = {"requested_instrument": "stocks", "objective": "best_ideas", "universes": ["large_cap"], "profiles": ["momentum_breakout"]}

    first = plan_fingerprint(plan, effective_tickers=["AAPL", "MSFT"])
    second = plan_fingerprint(plan, effective_tickers=["AAPL", "NVDA"])

    assert first != second
    assert len(first) == 16
