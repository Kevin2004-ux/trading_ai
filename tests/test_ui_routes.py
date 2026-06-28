import importlib.util
import asyncio
import time

import pytest

from planning.policy_validator import POLICY_LIMITS


FASTAPI_AVAILABLE = importlib.util.find_spec("fastapi") is not None
HTTPX_AVAILABLE = importlib.util.find_spec("httpx") is not None
UI_ROUTE_TEST_DEPS_AVAILABLE = FASTAPI_AVAILABLE and HTTPX_AVAILABLE

if UI_ROUTE_TEST_DEPS_AVAILABLE:
    from fastapi.testclient import TestClient

    from ui.app import app

    client = TestClient(app)
else:
    app = None
    client = None


@pytest.fixture(autouse=True)
def _force_deterministic_ai_planner(monkeypatch):
    monkeypatch.setenv("AI_PLANNER_PROVIDER", "deterministic")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)


def _fake_planned_execution(captured: dict, ticker: str = "AAPL", include_options: bool = False):
    def fake_execute_scan_plan(proposed_plan, runtime_context=None, db_path="strategy_library.db", internal_controls=None):
        plan_payload = proposed_plan.model_dump(mode="json") if hasattr(proposed_plan, "model_dump") else dict(proposed_plan or {})
        requested = plan_payload.get("requested_instrument", "stocks")
        resolved_include_options = include_options or requested == "options" or bool(plan_payload.get("include_options"))
        captured.update(
            {
                "proposed_plan": plan_payload,
                "runtime_context": runtime_context or {},
                "db_path": db_path,
                "include_options": resolved_include_options,
                "prefer_options": bool(plan_payload.get("prefer_options")),
                "internal_controls": dict(internal_controls or {}),
            }
        )
        explicit_scope = plan_payload.get("objective") == "ticker_review" or bool(plan_payload.get("custom_tickers"))
        discovery_enabled = bool((internal_controls or {}).get("use_dynamic_discovery")) and not explicit_scope
        discovery_summary = {
            "discovery_used": discovery_enabled,
            "discovered_count": 2 if discovery_enabled else 0,
            "sources_used": ["manual_hotlist"] if discovery_enabled else [],
            "requested_sources": list((internal_controls or {}).get("discovery_sources", [])),
            "tickers": ["MSFT", "NVDA"] if discovery_enabled else [],
            "top_candidates": [
                {
                    "ticker": "MSFT",
                    "discovery_score": 98,
                    "source_type": "manual_hotlist",
                    "reason_discovered": "Manual hotlist.",
                    "reasons": ["Manual hotlist."],
                    "requires_live_validation": True,
                    "point_in_time_safe": True,
                }
            ] if discovery_enabled else [],
            "warnings": [],
            "errors": [],
            "fallback_used": False,
            "bypass_reason": "explicit_ticker_scope" if explicit_scope else None,
            "point_in_time_safe": True,
            "requires_live_validation": True,
        }
        option_rows = [
            {"ticker": ticker, "asset_type": "option", "status": "research_only", "rank": 1, "opportunity_score": 70}
        ] if resolved_include_options else []
        provider_capabilities = [
            {
                "provider_name": "test_market_data",
                "provider_type": "market_data",
                "available": True,
                "authenticated": True,
                "entitlement_status": "available",
                "supports_realtime_quotes": True,
                "supports_historical_bars": True,
                "supports_options_chain": False,
                "supports_fundamentals": False,
                "supports_news": False,
                "supports_filings": False,
                "supports_short_interest": False,
                "rate_limited": False,
                "degraded": False,
                "last_checked_at": "2026-06-28T12:00:00+00:00",
                "warnings": [],
                "errors": [],
            }
        ]
        policy_validation = {
            "ok": True,
            "policy_version": "scan_policy_v1",
            "approved_plan": {
                "requested_instrument": requested,
                "include_options": resolved_include_options,
                "prefer_options": bool(plan_payload.get("prefer_options")),
                "universes": plan_payload.get("universes", ["large_cap", "active", "tech"]),
                "research_preferences": plan_payload.get("research_preferences", {}),
                "refinement": plan_payload.get("refinement", {"max_passes": 1}),
            },
            "execution_config": {
                "include_options": resolved_include_options,
                "prefer_options": bool(plan_payload.get("prefer_options")),
                "paper_trading_only": True,
                "brokerage_execution_enabled": False,
            },
        }
        return {
            "ok": True,
            "execution_version": "scan_plan_executor_v1",
            "paper_trading_only": True,
            "brokerage_execution_enabled": False,
            "policy_validation": policy_validation,
            "approved_plan": {
                "requested_instrument": requested,
                "include_options": resolved_include_options,
                "prefer_options": bool(plan_payload.get("prefer_options")),
                "universes": plan_payload.get("universes", ["large_cap", "active", "tech"]),
            },
            "execution_config": {
                "include_options": resolved_include_options,
                "prefer_options": bool(plan_payload.get("prefer_options")),
                "options_final_eligibility": False,
                "paper_trading_only": True,
                "brokerage_execution_enabled": False,
            },
            "execution_summary": {
                "status": "completed",
                "universes_requested": plan_payload.get("universes", ["large_cap", "active", "tech"]),
                "universes_used": plan_payload.get("universes", ["large_cap", "active", "tech"]),
                "auto_log": False,
                "include_options": resolved_include_options,
                "discovery_summary": discovery_summary,
                "provider_capabilities": provider_capabilities,
            },
            "discovery_summary": discovery_summary,
            "provider_capabilities": provider_capabilities,
            "discovery_result": {"discovery_used": discovery_summary["discovery_used"], "discovered_count": discovery_summary["discovered_count"], "tickers": discovery_summary["tickers"]},
            "trading_result": {"ok": True, "decision_result": {"logged_recommendations": []}, "discovery_summary": discovery_summary, "provider_capabilities": provider_capabilities},
            "option_discovery": {
                "status": "available" if resolved_include_options else "disabled",
                "options_final_eligibility": False,
                "paper_eligible_contracts": [],
                "research_only_contracts": [],
                "blocked_contracts": [],
                "underlying_watchlist": [],
            },
            "best_available_ideas": {
                "ok": True,
                "ranking_status": "available",
                "option_discovery_status": "available" if resolved_include_options else "disabled",
                "option_data_missing": [],
                "paper_eligible": [],
                "stock_watchlist": [
                    {"ticker": ticker, "asset_type": "stock", "recommendation_status": "watchlist", "score": 80, "idea_score": 80}
                ],
                "option_research_only": [
                    {"ticker": ticker, "asset_type": "option", "recommendation_status": "research_only", "score": 70, "idea_score": 70}
                ] if resolved_include_options else [],
                "option_underlying_watchlist": [],
                "blocked_but_interesting": [],
                "why_no_final_trades": ["No final paper trades passed strict objective gates."],
                "data_missing": [],
                "system_issues": [],
                "next_steps": [],
                "warnings": [],
            },
            "assistant_response": {
                "ok": True,
                "response_type": "trade_ideas",
                "paper_trading_only": True,
                "ranking_status": "available",
                "requested_instrument": requested,
                "market_state": {
                    "provider_status": "available",
                    "market_regime": None,
                    "data_freshness": None,
                    "partial_results": False,
                    "discovery_used": discovery_summary["discovery_used"],
                    "discovered_count": discovery_summary["discovered_count"],
                    "sources_used": discovery_summary["sources_used"],
                    "discovery_summary": discovery_summary,
                    "provider_capabilities": provider_capabilities,
                    "message": None,
                },
                "top_stocks": [
                    {"ticker": ticker, "asset_type": "stock", "status": "watchlist", "rank": 1, "opportunity_score": 80}
                ] if requested != "options" else [],
                "top_options": option_rows,
                "option_underlying_watchlist": [],
                "option_discovery_status": "available" if resolved_include_options else "disabled",
                "option_data_missing": [],
                "paper_eligible": [],
                "research_only": [],
                "blocked": [],
                "why_no_final_trades": ["No final paper trades passed strict objective gates."],
                "data_missing": [],
                "system_issues": [],
                "next_steps": [],
                "scan_summary": {"include_options": resolved_include_options, "profiles_run": []},
                "refinement": {"used": False, "passes_executed": 1, "stop_reason": "", "changes": [], "warnings": []},
            },
            "formatted_response": "No final paper trades passed strict gates today.\nTop stock research ideas:",
            "warnings": [],
            "errors": [],
        }

    return fake_execute_scan_plan


def _fake_adaptive_execution(captured: dict, ticker: str = "AAPL", include_options: bool = False):
    single_scan = _fake_planned_execution(captured, ticker=ticker, include_options=include_options)

    def fake_execute_adaptive_scan_plan(proposed_plan, runtime_context=None, db_path="strategy_library.db", message=None, provider=None, internal_controls=None):
        base = single_scan(proposed_plan, runtime_context=runtime_context, db_path=db_path, internal_controls=internal_controls)
        assistant = dict(base["assistant_response"])
        assistant["refinement"] = {
            "used": False,
            "passes_executed": 1,
            "stop_reason": "Sufficient legitimate research results found.",
            "changes": [],
            "warnings": [],
        }
        return {
            "ok": True,
            "adaptive_execution_version": "adaptive_scan_v1",
            "paper_trading_only": True,
            "brokerage_execution_enabled": False,
            "status": "completed",
            "request_id": "adaptive-test",
            "root_run_id": "adaptive-test",
            "initial_plan": base["policy_validation"]["approved_plan"],
            "initial_policy_validation": base["policy_validation"],
            "max_passes": 2,
            "passes_executed": 1,
            "stop_reason": "Sufficient legitimate research results found.",
            "refinement_used": False,
            "refinement_provider": "none",
            "discovery_result": base["discovery_result"],
            "discovery_summary": base["discovery_summary"],
            "provider_capabilities": base["provider_capabilities"],
            "passes": [
                {
                    "pass_number": 1,
                    "run_id": "adaptive-test:pass-1",
                    "parent_run_id": "adaptive-test",
                    "plan_fingerprint": "fakefingerprint1",
                    "proposed_plan": proposed_plan,
                    "policy_validation": base["policy_validation"],
                    "approved_plan": base["policy_validation"]["approved_plan"],
                    "execution_summary": base["execution_summary"],
                    "evaluation": {"ranking_status": "available", "sufficient_results": True},
                    "refinement_proposal": None,
                    "result_summary": {"ranking_status": "available"},
                    "execution_result": base,
                    "warnings": [],
                    "errors": [],
                }
            ],
            "consolidated_result": base["trading_result"],
            "best_available_ideas": base["best_available_ideas"],
            "assistant_response": assistant,
            "option_discovery": base["option_discovery"],
            "research": {"ok": True, "status": "disabled", "dossiers": [], "warnings": [], "errors": []},
            "formatted_response": base["formatted_response"],
            "warnings": [],
            "errors": [],
        }

    return fake_execute_adaptive_scan_plan


def test_ui_route_test_dependencies_are_present_or_reported_cleanly():
    if not UI_ROUTE_TEST_DEPS_AVAILABLE:
        pytest.skip("fastapi/httpx is not installed in the local test environment.")

    assert client is not None


@pytest.mark.skipif(not UI_ROUTE_TEST_DEPS_AVAILABLE, reason="fastapi/httpx is not installed in the local test environment.")
def test_ui_app_exposes_expected_route_paths():
    route_paths = {route.path for route in app.routes}

    assert "/health" in route_paths
    assert "/diagnostics/environment" in route_paths
    assert "/diagnostics/live-dry-run" in route_paths
    assert "/brain/weekly-trade-hunt" in route_paths
    assert "/brain/review-ticker/{ticker}" in route_paths
    assert "/brain/monitor-open-trades" in route_paths
    assert "/paper/cycle" in route_paths
    assert "/paper/review" in route_paths
    assert "/paper/summary" in route_paths
    assert "/reports/generate" in route_paths
    assert "/reports/paper-summary" in route_paths
    assert "/journal/review-closed-trades" in route_paths
    assert "/journal/reviews" in route_paths
    assert "/trades/open" in route_paths
    assert "/trades/performance" in route_paths
    assert "/trades/update-outcomes" in route_paths
    assert "/api/status" in route_paths
    assert "/api/frontend-debug" in route_paths
    assert "/api/readiness" in route_paths
    assert "/api/db-status" in route_paths
    assert "/api/trades" in route_paths
    assert "/api/trades/{recommendation_id}" in route_paths
    assert "/api/performance" in route_paths
    assert "/api/alerts" in route_paths
    assert "/api/jobs" in route_paths
    assert "/api/reports/performance" in route_paths
    assert "/api/stress/scenarios" in route_paths
    assert "/api/planning/validate" in route_paths
    assert "/api/planning/propose" in route_paths
    assert "/api/planning/execute" in route_paths
    assert "/api/planning/execute-adaptive" in route_paths
    assert "/api/research/current" in route_paths
    assert "/api/learning/status" in route_paths
    assert "/api/learning/grade-outcomes" in route_paths
    assert "/api/learning/evaluate-policy" in route_paths
    assert "/api/learning/proposals" in route_paths
    assert "/api/learning/promote" in route_paths
    assert "/api/learning/policies" in route_paths
    assert "/api/chat" in route_paths
    assert "/api/scan" in route_paths
    assert "/api/options/strategies" in route_paths
    assert "/api/options/discover" in route_paths
    assert "/api/annotations" in route_paths
    assert "/api/system/config-check" in route_paths
    assert "/api/system/readiness-check" in route_paths
    assert "/api/system/live-dry-run" in route_paths
    assert "/trade/execute" not in route_paths
    assert "/orders" not in route_paths
    assert "/buy" not in route_paths
    assert "/sell" not in route_paths
    for path in route_paths:
        normalized_path = path.lower()
        assert "brokerage" not in normalized_path
        if normalized_path not in {"/api/planning/execute", "/api/planning/execute-adaptive"}:
            assert "execute" not in normalized_path
        assert "/order" not in normalized_path
        assert "/buy" not in normalized_path
        assert "/sell" not in normalized_path


@pytest.mark.skipif(not UI_ROUTE_TEST_DEPS_AVAILABLE, reason="fastapi/httpx is not installed in the local test environment.")
def test_health_route_returns_ok():
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {
        "ok": True,
        "service": "trading_ai",
        "status": "running",
    }


@pytest.mark.skipif(not UI_ROUTE_TEST_DEPS_AVAILABLE, reason="fastapi/httpx is not installed in the local test environment.")
def test_root_route_returns_dashboard_html():
    response = client.get("/")

    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    body = response.text
    assert "Trading AI Dashboard" in body
    assert "Paper trading only" in body
    assert "No live brokerage execution" in body
    assert "Reports summarize system outputs and are not financial advice" in body


@pytest.mark.skipif(not UI_ROUTE_TEST_DEPS_AVAILABLE, reason="fastapi/httpx is not installed in the local test environment.")
def test_dashboard_html_includes_paper_cycle_review_reports_and_research_sections():
    response = client.get("/")

    assert response.status_code == 200
    body = response.text
    assert "Weekly Paper Cycle" in body
    assert "Run Paper Cycle" in body
    assert "Paper Review" in body
    assert "Review Paper Portfolio" in body
    assert "Reports" in body
    assert "Generate Report" in body
    assert "Ticker Research" in body
    assert "Generate Research Brief" in body
    assert "Check health" in body
    assert "Diagnostics" in body
    assert "Environment Check" in body
    assert "Run Live Provider Dry Run" in body
    assert "Dry run only" in body
    assert "No trades are placed" in body
    assert "Provider calls may use live API quotas" in body


@pytest.mark.skipif(not UI_ROUTE_TEST_DEPS_AVAILABLE, reason="fastapi/httpx is not installed in the local test environment.")
def test_diagnostics_environment_route_returns_healthcheck(monkeypatch):
    monkeypatch.setattr(
        "ui.app.check_environment",
        lambda db_path="strategy_library.db": {
            "ok": True,
            "timestamp": "2026-06-08T00:00:00+00:00",
            "python_version": "3.11",
            "packages": {},
            "env_vars": {},
            "database": {"ok": True},
            "app": {"ok": True},
            "cli": {"ok": True},
            "warnings": [],
            "errors": [],
        },
    )

    response = client.get("/diagnostics/environment")

    assert response.status_code == 200
    assert response.json()["ok"] is True
    assert response.json()["database"]["ok"] is True


@pytest.mark.skipif(not UI_ROUTE_TEST_DEPS_AVAILABLE, reason="fastapi/httpx is not installed in the local test environment.")
def test_diagnostics_live_dry_run_route_returns_summary(monkeypatch):
    captured = {}
    monkeypatch.setattr(
        "ui.app.run_provider_dry_run",
        lambda **kwargs: captured.update(kwargs) or {
            "ok": True,
            "timestamp": "2026-06-08T00:00:00+00:00",
            "ticker": kwargs["ticker"],
            "checks": {},
            "warnings": ["dry run"],
            "errors": [],
        },
    )

    response = client.post("/diagnostics/live-dry-run", json={"ticker": "AAPL", "include_memory": True})

    assert response.status_code == 200
    assert response.json()["ticker"] == "AAPL"
    assert captured["include_memory"] is True


@pytest.mark.skipif(not UI_ROUTE_TEST_DEPS_AVAILABLE, reason="fastapi/httpx is not installed in the local test environment.")
def test_planning_validate_route_is_diagnostic_only(monkeypatch):
    def forbidden_scan(**kwargs):
        raise AssertionError("Planning validation route must not execute scans.")

    monkeypatch.setattr("ui.app.run_paper_trade_cycle", forbidden_scan)
    monkeypatch.setattr("ui.app.run_weekly_trade_hunt", forbidden_scan)

    response = client.post(
        "/api/planning/validate",
        json={
            "plan": {
                "requested_instrument": "stocks",
                "include_options": True,
                "universes": ["fake", "large_cap"],
            },
            "runtime_context": {"safe_to_run_options": False},
        },
    )

    payload = response.json()
    assert response.status_code == 200
    assert payload["ok"] is True
    assert payload["policy_version"] == "scan_policy_v1"
    assert payload["execution_config"]["include_options"] is False
    assert payload["execution_config"]["brokerage_execution_enabled"] is False
    assert "large_cap" in payload["execution_config"]["universes"]


@pytest.mark.skipif(not UI_ROUTE_TEST_DEPS_AVAILABLE, reason="fastapi/httpx is not installed in the local test environment.")
def test_planning_propose_route_is_non_executing(monkeypatch):
    def forbidden_scan(*args, **kwargs):
        raise AssertionError("Planning proposal route must not execute scans or trades.")

    monkeypatch.setattr("ui.app.execute_scan_plan", forbidden_scan)
    monkeypatch.setattr("ui.app.execute_adaptive_scan_plan", forbidden_scan)
    monkeypatch.setattr("ui.app.run_paper_trade_cycle", forbidden_scan)
    monkeypatch.setattr("ui.app.run_weekly_trade_hunt", forbidden_scan)

    response = client.post(
        "/api/planning/propose",
        json={
            "message": "Give me best stock ideas. Do not include options.",
            "runtime_context": {"safe_to_run_options": False},
            "request_id": "ui-propose-1",
            "provider": "deterministic",
        },
    )

    payload = response.json()
    assert response.status_code == 200
    assert payload["ok"] is True
    assert payload["planner_version"] == "ai_scan_planner_v1"
    assert payload["status"] == "deterministic_planned"
    assert payload["approved_plan"]["requested_instrument"] == "stocks"
    assert payload["approved_plan"]["include_options"] is False
    assert payload["policy_validation"]["execution_config"]["brokerage_execution_enabled"] is False


@pytest.mark.skipif(not UI_ROUTE_TEST_DEPS_AVAILABLE, reason="fastapi/httpx is not installed in the local test environment.")
def test_research_current_route_is_research_only(monkeypatch):
    captured = {}

    def forbidden_scan(*args, **kwargs):
        raise AssertionError("Research route must not execute scans, trading brain, logging, or brokerage logic.")

    monkeypatch.setattr("ui.app.execute_scan_plan", forbidden_scan)
    monkeypatch.setattr("ui.app.execute_adaptive_scan_plan", forbidden_scan)
    monkeypatch.setattr("ui.app.run_paper_trade_cycle", forbidden_scan)
    monkeypatch.setattr("ui.app.run_weekly_trade_hunt", forbidden_scan)
    monkeypatch.setattr(
        "ui.app.build_current_research",
        lambda tickers, **kwargs: captured.update({"tickers": tickers, **kwargs}) or {
            "ok": True,
            "research_version": "current_research_v1",
            "status": "available",
            "provider": "local",
            "model": None,
            "request_id": kwargs.get("request_id"),
            "as_of": "2026-06-22T12:00:00Z",
            "web_search_used": False,
            "local_research_used": True,
            "cache_hit": False,
            "tickers_requested": tickers,
            "tickers_researched": tickers,
            "scopes_requested": kwargs.get("scopes") or [],
            "dossiers": [],
            "sources": [],
            "warnings": [],
            "errors": [],
            "usage": {"input_tokens": None, "output_tokens": None, "total_tokens": None, "web_search_calls": 0, "extraction_calls": 0},
        },
    )

    response = client.post(
        "/api/research/current",
        json={"tickers": ["AAPL"], "scopes": ["company_news"], "provider": "local", "request_id": "research-route-1"},
    )

    payload = response.json()
    assert response.status_code == 200
    assert payload["ok"] is True
    assert payload["research_version"] == "current_research_v1"
    assert captured["tickers"] == ["AAPL"]
    assert captured["provider"] == "local"


@pytest.mark.skipif(not UI_ROUTE_TEST_DEPS_AVAILABLE, reason="fastapi/httpx is not installed in the local test environment.")
def test_learning_status_route_returns_learning_readiness(monkeypatch):
    captured = {}
    monkeypatch.setattr(
        "ui.app.get_learning_status",
        lambda db_path="strategy_library.db": captured.update({"db_path": db_path}) or {
            "ok": True,
            "learning_version": "research_learning_v1",
            "status": "collecting_data",
            "active_policy_version": "research_policy_v1_baseline",
            "promotion_ready": False,
            "warnings": [],
            "errors": [],
        },
    )

    response = client.get("/api/learning/status?db_path=test-learning.db")

    payload = response.json()
    assert response.status_code == 200
    assert payload["ok"] is True
    assert payload["learning_version"] == "research_learning_v1"
    assert payload["promotion_ready"] is False
    assert captured["db_path"] == "test-learning.db"


@pytest.mark.skipif(not UI_ROUTE_TEST_DEPS_AVAILABLE, reason="fastapi/httpx is not installed in the local test environment.")
def test_learning_grade_outcomes_route_calls_grader(monkeypatch):
    captured = {}
    monkeypatch.setattr(
        "ui.app.grade_mature_candidate_outcomes",
        lambda **kwargs: captured.update(kwargs) or {
            "ok": True,
            "grading_version": "candidate_outcome_v1",
            "snapshots_considered": 1,
            "outcomes_created": 1,
            "warnings": [],
            "errors": [],
        },
    )

    response = client.post(
        "/api/learning/grade-outcomes",
        json={"db_path": "test-learning.db", "as_of": "2026-06-22", "horizons": [5, 10]},
    )

    payload = response.json()
    assert response.status_code == 200
    assert payload["ok"] is True
    assert payload["grading_version"] == "candidate_outcome_v1"
    assert captured == {"db_path": "test-learning.db", "as_of": "2026-06-22", "horizons": [5, 10]}


@pytest.mark.skipif(not UI_ROUTE_TEST_DEPS_AVAILABLE, reason="fastapi/httpx is not installed in the local test environment.")
def test_learning_evaluate_policy_route_is_diagnostic_only(monkeypatch):
    captured = {}

    def forbidden_scan(*args, **kwargs):
        raise AssertionError("Learning policy evaluation must not execute scans or trades.")

    monkeypatch.setattr("ui.app.run_paper_trade_cycle", forbidden_scan)
    monkeypatch.setattr("ui.app.run_weekly_trade_hunt", forbidden_scan)
    monkeypatch.setattr(
        "ui.app.evaluate_policy_walk_forward",
        lambda candidate_policy, **kwargs: captured.update({"candidate_policy": candidate_policy, **kwargs}) or {
            "ok": True,
            "evaluation_version": "policy_walk_forward_v1",
            "status": "insufficient_data",
            "promotion_eligibility": {"promotion_eligible": False, "automatic_promotion_allowed": False},
            "warnings": [],
            "errors": [],
        },
    )

    response = client.post(
        "/api/learning/evaluate-policy",
        json={
            "candidate_policy": {"policy_version": "research_policy_v1"},
            "baseline_policy_version": "research_policy_v1_baseline",
            "config": {"horizon_sessions": 5},
            "db_path": "test-learning.db",
        },
    )

    payload = response.json()
    assert response.status_code == 200
    assert payload["ok"] is True
    assert payload["promotion_eligibility"]["automatic_promotion_allowed"] is False
    assert captured["candidate_policy"]["policy_version"] == "research_policy_v1"
    assert captured["baseline_policy_version"] == "research_policy_v1_baseline"
    assert captured["db_path"] == "test-learning.db"


@pytest.mark.skipif(not UI_ROUTE_TEST_DEPS_AVAILABLE, reason="fastapi/httpx is not installed in the local test environment.")
def test_learning_proposals_and_policies_routes_are_research_only(monkeypatch):
    captured = {}
    monkeypatch.setattr(
        "ui.app.create_policy_proposal",
        lambda proposed_policy, **kwargs: captured.update({"proposed_policy": proposed_policy, **kwargs}) or {
            "ok": True,
            "proposal": {"id": 1, "status": "shadow", "promotion_eligibility_json": {"promotion_eligible": False}},
            "evaluation": {"status": "insufficient_data"},
            "errors": [],
            "warnings": [],
        },
    )
    monkeypatch.setattr(
        "ui.app.list_policies",
        lambda db_path="strategy_library.db", include_policy_json=True: {
            "ok": True,
            "policies": [{"policy_version": "research_policy_v1_baseline", "status": "active"}],
            "count": 1,
            "errors": [],
        },
    )

    proposal_response = client.post(
        "/api/learning/proposals",
        json={"proposed_policy": {"policy_version": "research_policy_v1"}, "created_by": "tester", "db_path": "test-learning.db"},
    )
    policies_response = client.get("/api/learning/policies?db_path=test-learning.db")

    assert proposal_response.status_code == 200
    assert proposal_response.json()["proposal"]["status"] == "shadow"
    assert captured["created_by"] == "tester"
    assert captured["db_path"] == "test-learning.db"
    assert policies_response.status_code == 200
    assert policies_response.json()["policies"][0]["status"] == "active"


@pytest.mark.skipif(not UI_ROUTE_TEST_DEPS_AVAILABLE, reason="fastapi/httpx is not installed in the local test environment.")
def test_learning_promote_route_requires_manual_confirmation(monkeypatch):
    captured = {}
    monkeypatch.setattr(
        "ui.app.promote_policy_proposal",
        lambda **kwargs: captured.update(kwargs) or {
            "ok": False,
            "promoted": False,
            "errors": ["confirm must be true for manual promotion."],
            "warnings": [],
        },
    )

    response = client.post(
        "/api/learning/promote",
        json={
            "proposal_id": 1,
            "approved_by": "human",
            "approval_reason": "manual review",
            "expected_current_policy_version": "research_policy_v1_baseline",
            "confirm": False,
            "db_path": "test-learning.db",
        },
    )

    payload = response.json()
    assert response.status_code == 200
    assert payload["ok"] is False
    assert payload["promoted"] is False
    assert captured["confirm"] is False
    assert captured["approved_by"] == "human"


@pytest.mark.skipif(not UI_ROUTE_TEST_DEPS_AVAILABLE, reason="fastapi/httpx is not installed in the local test environment.")
def test_planning_execute_route_calls_executor_without_logging(monkeypatch):
    captured = {}
    monkeypatch.setattr("ui.app.execute_scan_plan", _fake_planned_execution(captured, ticker="AAPL"))

    response = client.post(
        "/api/planning/execute",
        json={
            "plan": {"requested_instrument": "stocks", "universes": ["large_cap"], "max_tickers": 3},
            "runtime_context": {"safe_to_run_options": False},
            "db_path": "test.db",
        },
    )

    payload = response.json()
    assert response.status_code == 200
    assert payload["ok"] is True
    assert payload["execution_summary"]["auto_log"] is False
    assert payload["brokerage_execution_enabled"] is False
    assert payload["trading_result"]["decision_result"]["logged_recommendations"] == []
    assert captured["db_path"] == "test.db"


@pytest.mark.skipif(not UI_ROUTE_TEST_DEPS_AVAILABLE, reason="fastapi/httpx is not installed in the local test environment.")
def test_planning_execute_adaptive_route_calls_adaptive_executor(monkeypatch):
    captured = {}
    monkeypatch.setattr("ui.app.execute_adaptive_scan_plan", _fake_adaptive_execution(captured, ticker="AAPL"))

    response = client.post(
        "/api/planning/execute-adaptive",
        json={
            "plan": {"requested_instrument": "stocks", "universes": ["large_cap"], "max_tickers": 3, "refinement": {"max_passes": 2}},
            "runtime_context": {"safe_to_run_options": False},
            "message": "Best stock ideas. No options.",
            "provider": "deterministic",
            "db_path": "test.db",
        },
    )

    payload = response.json()
    assert response.status_code == 200
    assert payload["ok"] is True
    assert payload["adaptive_execution_version"] == "adaptive_scan_v1"
    assert payload["brokerage_execution_enabled"] is False
    assert payload["paper_trading_only"] is True
    assert payload["consolidated_result"]["decision_result"]["logged_recommendations"] == []
    assert captured["db_path"] == "test.db"


@pytest.mark.skipif(not UI_ROUTE_TEST_DEPS_AVAILABLE, reason="fastapi/httpx is not installed in the local test environment.")
def test_weekly_trade_hunt_route_calls_brain_with_auto_log_false_by_default(monkeypatch):
    captured = {}

    def fake_run_weekly_trade_hunt(**kwargs):
        captured.update(kwargs)
        return {
            "ok": True,
            "mode": "weekly_trade_hunt",
            "timestamp": "2026-06-05T00:00:00+00:00",
            "universe_result": {},
            "scan_result": {},
            "selection_result": {},
            "decision_result": {},
            "performance_context": {},
            "summary": {"tickers_scanned": 0, "profiles_run": [], "selected_count": 0, "logged_count": 0, "message": "ok"},
            "errors": [],
        }

    monkeypatch.setattr("ui.app.run_weekly_trade_hunt", fake_run_weekly_trade_hunt)

    response = client.post("/brain/weekly-trade-hunt", json={})

    assert response.status_code == 200
    assert response.json()["ok"] is True
    assert captured["auto_log"] is False


@pytest.mark.skipif(not UI_ROUTE_TEST_DEPS_AVAILABLE, reason="fastapi/httpx is not installed in the local test environment.")
def test_weekly_trade_hunt_route_supports_auto_log_true(monkeypatch):
    captured = {}

    def fake_run_weekly_trade_hunt(**kwargs):
        captured.update(kwargs)
        return {
            "ok": True,
            "mode": "weekly_trade_hunt",
            "timestamp": "2026-06-05T00:00:00+00:00",
            "universe_result": {},
            "scan_result": {},
            "selection_result": {},
            "decision_result": {},
            "performance_context": {},
            "summary": {"tickers_scanned": 0, "profiles_run": [], "selected_count": 0, "logged_count": 1, "message": "ok"},
            "errors": [],
        }

    monkeypatch.setattr("ui.app.run_weekly_trade_hunt", fake_run_weekly_trade_hunt)

    response = client.post("/brain/weekly-trade-hunt", json={"auto_log": True})

    assert response.status_code == 200
    assert response.json()["ok"] is True
    assert captured["auto_log"] is True


@pytest.mark.skipif(not UI_ROUTE_TEST_DEPS_AVAILABLE, reason="fastapi/httpx is not installed in the local test environment.")
def test_weekly_trade_hunt_route_accepts_option_fields(monkeypatch):
    captured = {}

    def fake_run_weekly_trade_hunt(**kwargs):
        captured.update(kwargs)
        return {
            "ok": True,
            "mode": "weekly_trade_hunt",
            "timestamp": "2026-06-05T00:00:00+00:00",
            "universe_result": {},
            "scan_result": {},
            "selection_result": {},
            "decision_result": {},
            "performance_context": {},
            "summary": {"tickers_scanned": 0, "profiles_run": [], "selected_count": 0, "logged_count": 0, "message": "ok"},
            "errors": [],
        }

    monkeypatch.setattr("ui.app.run_weekly_trade_hunt", fake_run_weekly_trade_hunt)

    response = client.post("/brain/weekly-trade-hunt", json={"include_options": True, "prefer_options": True, "max_option_contracts_per_trade": 2})

    assert response.status_code == 200
    assert captured["include_options"] is True
    assert captured["prefer_options"] is True
    assert captured["max_option_contracts_per_trade"] == 2


@pytest.mark.skipif(not UI_ROUTE_TEST_DEPS_AVAILABLE, reason="fastapi/httpx is not installed in the local test environment.")
def test_review_ticker_route_returns_structured_review(monkeypatch):
    monkeypatch.setattr(
        "ui.app.review_ticker_opportunity",
        lambda **kwargs: {
            "ok": True,
            "mode": "review_ticker",
            "timestamp": "2026-06-05T00:00:00+00:00",
            "ticker": kwargs["ticker"],
            "status": "recommendable",
            "decision": {"ticker": kwargs["ticker"]},
            "reasons": ["Passed objective constraints."],
        },
    )

    response = client.get("/brain/review-ticker/AAPL")

    assert response.status_code == 200
    assert response.json()["ok"] is True
    assert response.json()["ticker"] == "AAPL"


@pytest.mark.skipif(not UI_ROUTE_TEST_DEPS_AVAILABLE, reason="fastapi/httpx is not installed in the local test environment.")
def test_review_ticker_route_returns_when_vix_context_warns(monkeypatch):
    monkeypatch.setattr(
        "ui.app.review_ticker_opportunity",
        lambda **kwargs: {
            "ok": True,
            "mode": "review_ticker",
            "timestamp": "2026-06-05T00:00:00+00:00",
            "ticker": kwargs["ticker"],
            "status": "watchlist",
            "decision": {"ticker": kwargs["ticker"], "decision": "watchlist"},
            "reasons": ["VIX unavailable; using SPY ATR volatility context."],
            "research_brief": {
                "market_regime": {
                    "ok": True,
                    "index_context": {"VIX": {"source": "SPY_ATR"}},
                    "warnings": ["VIX unavailable; using SPY ATR volatility context."],
                }
            },
        },
    )

    response = client.get("/brain/review-ticker/AAPL")
    payload = response.json()

    assert response.status_code == 200
    assert payload["ok"] is True
    assert payload["ticker"] == "AAPL"
    assert "VIX unavailable" in payload["reasons"][0]
    assert payload["research_brief"]["market_regime"]["index_context"]["VIX"]["source"] == "SPY_ATR"


@pytest.mark.skipif(not UI_ROUTE_TEST_DEPS_AVAILABLE, reason="fastapi/httpx is not installed in the local test environment.")
def test_review_ticker_route_returns_ranking_unavailable_provider_warning(monkeypatch):
    provider_error = "IBKR client ID is already in use. Close stale TWS sessions or use a unique IBKR_CLIENT_ID."
    monkeypatch.setattr(
        "ui.app.review_ticker_opportunity",
        lambda **kwargs: {
            "ok": True,
            "mode": "review_ticker",
            "timestamp": "2026-06-05T00:00:00+00:00",
            "ticker": kwargs["ticker"],
            "status": "ranking_unavailable",
            "candidate": None,
            "decision": None,
            "reasons": [provider_error],
            "warnings": [provider_error],
            "market_snapshot": {"ok": False, "error": provider_error, "error_type": "provider"},
        },
    )

    response = client.get("/brain/review-ticker/AAPL")
    payload = response.json()

    assert response.status_code == 200
    assert payload["ok"] is True
    assert payload["status"] == "ranking_unavailable"
    assert payload["warnings"] == [provider_error]


@pytest.mark.skipif(not UI_ROUTE_TEST_DEPS_AVAILABLE, reason="fastapi/httpx is not installed in the local test environment.")
def test_monitor_open_trades_route_returns_structured_result(monkeypatch):
    monkeypatch.setattr(
        "ui.app.monitor_open_trades",
        lambda update_outcomes=True, db_path="strategy_library.db": {
            "ok": True,
            "mode": "monitor_open_trades",
            "timestamp": "2026-06-05T00:00:00+00:00",
            "open_recommendations": [],
            "performance_context": {"win_loss_record": {}, "strategy_performance": {}},
            "summary": {"open_trade_count": 0, "message": "ok"},
            "errors": [],
        },
    )

    response = client.post("/brain/monitor-open-trades", json={})

    assert response.status_code == 200
    assert response.json()["ok"] is True
    assert response.json()["mode"] == "monitor_open_trades"


@pytest.mark.skipif(not UI_ROUTE_TEST_DEPS_AVAILABLE, reason="fastapi/httpx is not installed in the local test environment.")
def test_trades_open_route_returns_open_recommendations(monkeypatch):
    monkeypatch.setattr("ui.app.get_open_recommendations", lambda db_path="strategy_library.db": [{"ticker": "AAPL"}])

    response = client.get("/trades/open")

    assert response.status_code == 200
    assert response.json()["ok"] is True
    assert response.json()["recommendations"][0]["ticker"] == "AAPL"


@pytest.mark.skipif(not UI_ROUTE_TEST_DEPS_AVAILABLE, reason="fastapi/httpx is not installed in the local test environment.")
def test_trades_performance_route_returns_performance(monkeypatch):
    monkeypatch.setattr("ui.app.get_win_loss_record", lambda db_path="strategy_library.db": {"wins": 1, "losses": 0, "win_rate": 100.0})
    monkeypatch.setattr("ui.app.get_strategy_performance", lambda db_path="strategy_library.db": {"overall": {"total_recommendations": 1}})

    response = client.get("/trades/performance")

    assert response.status_code == 200
    assert response.json()["ok"] is True
    assert response.json()["win_loss_record"]["wins"] == 1
    assert response.json()["strategy_performance"]["overall"]["total_recommendations"] == 1


@pytest.mark.skipif(not UI_ROUTE_TEST_DEPS_AVAILABLE, reason="fastapi/httpx is not installed in the local test environment.")
def test_trades_update_outcomes_route_returns_summary(monkeypatch):
    monkeypatch.setattr(
        "ui.app.update_open_recommendations",
        lambda db_path="strategy_library.db": {
            "ok": True,
            "checked": 1,
            "updated": 1,
            "still_open": 0,
            "manual_review": 0,
            "errors": [],
            "results": [{"recommendation_id": 1, "outcome": "win"}],
        },
    )

    response = client.post("/trades/update-outcomes", json={})

    assert response.status_code == 200
    assert response.json()["ok"] is True
    assert response.json()["updated"] == 1


@pytest.mark.skipif(not UI_ROUTE_TEST_DEPS_AVAILABLE, reason="fastapi/httpx is not installed in the local test environment.")
def test_route_errors_return_clean_json(monkeypatch):
    monkeypatch.setattr("ui.app.run_weekly_trade_hunt", lambda **kwargs: {"ok": False, "errors": ["boom"]})

    response = client.post("/brain/weekly-trade-hunt", json={})

    assert response.status_code == 500
    assert response.json()["ok"] is False
    assert response.json()["error"] == "boom"


@pytest.mark.skipif(not UI_ROUTE_TEST_DEPS_AVAILABLE, reason="fastapi/httpx is not installed in the local test environment.")
def test_paper_cycle_route_returns_structured_result(monkeypatch):
    captured = {}
    monkeypatch.setattr(
        "ui.app.run_paper_trade_cycle",
        lambda **kwargs: captured.update(kwargs) or {
            "ok": True,
            "mode": "paper_trading",
            "timestamp": "2026-06-05T00:00:00+00:00",
            "paper_trades_logged": [{"ticker": "AAPL"}],
            "summary": {"logged_count": 1, "message": "simulated"},
            "warning": "simulated only",
            "errors": [],
        },
    )

    response = client.post("/paper/cycle", json={"include_options": True, "prefer_options": True, "max_option_contracts_per_trade": 2})

    assert response.status_code == 200
    assert response.json()["mode"] == "paper_trading"
    assert "best_available_ideas" in response.json()
    assert captured["include_options"] is True
    assert captured["prefer_options"] is True
    assert captured["max_option_contracts_per_trade"] == 2


@pytest.mark.skipif(not UI_ROUTE_TEST_DEPS_AVAILABLE, reason="fastapi/httpx is not installed in the local test environment.")
def test_paper_review_route_returns_structured_result(monkeypatch):
    captured = {}
    monkeypatch.setattr(
        "ui.app.review_paper_portfolio",
        lambda **kwargs: captured.update(kwargs) or {
            "ok": True,
            "mode": "paper_trading",
            "timestamp": "2026-06-05T00:00:00+00:00",
            "trade_review_summary": {"reviewed_count": 0},
            "warning": "simulated only",
            "errors": [],
        },
    )

    response = client.post("/paper/review", json={"include_trade_reviews": False, "store_review_memory": True})

    assert response.status_code == 200
    assert response.json()["mode"] == "paper_trading"
    assert captured["include_trade_reviews"] is False
    assert captured["store_review_memory"] is True


@pytest.mark.skipif(not UI_ROUTE_TEST_DEPS_AVAILABLE, reason="fastapi/httpx is not installed in the local test environment.")
def test_paper_summary_route_returns_structured_result(monkeypatch):
    monkeypatch.setattr(
        "ui.app.get_paper_trading_summary",
        lambda **kwargs: {
            "ok": True,
            "mode": "paper_trading",
            "timestamp": "2026-06-05T00:00:00+00:00",
            "warning": "simulated only",
            "errors": [],
        },
    )

    response = client.get("/paper/summary")

    assert response.status_code == 200
    assert response.json()["mode"] == "paper_trading"


@pytest.mark.skipif(not UI_ROUTE_TEST_DEPS_AVAILABLE, reason="fastapi/httpx is not installed in the local test environment.")
def test_reports_generate_route_returns_structured_report(monkeypatch):
    captured = {}
    monkeypatch.setattr(
        "ui.app.generate_report_tool",
        lambda **kwargs: captured.update(kwargs) or {
            "ok": True,
            "tool": "generate_report_tool",
            "data": {"report_type": kwargs["report_type"], "format": kwargs["format"], "markdown": "# Report"},
            "error": None,
        },
    )

    response = client.post("/reports/generate", json={"report_type": "performance", "format": "dict", "payload": {}})

    assert response.status_code == 200
    assert response.json()["tool"] == "generate_report_tool"
    assert captured["report_type"] == "performance"
    assert captured["format"] == "dict"


@pytest.mark.skipif(not UI_ROUTE_TEST_DEPS_AVAILABLE, reason="fastapi/httpx is not installed in the local test environment.")
def test_reports_paper_summary_route_returns_report(monkeypatch):
    captured = {}
    monkeypatch.setattr(
        "ui.app.generate_report_tool",
        lambda **kwargs: captured.update(kwargs) or {
            "ok": True,
            "tool": "generate_report_tool",
            "data": {"report_type": "full_paper_trading", "format": kwargs["format"], "markdown": "# Full Paper Trading Report"},
            "error": None,
        },
    )

    response = client.get("/reports/paper-summary?format=markdown")

    assert response.status_code == 200
    assert response.json()["tool"] == "generate_report_tool"
    assert captured["report_type"] == "full_paper_trading"


@pytest.mark.skipif(not UI_ROUTE_TEST_DEPS_AVAILABLE, reason="fastapi/httpx is not installed in the local test environment.")
def test_journal_review_closed_trades_route_returns_summary(monkeypatch):
    captured = {}
    monkeypatch.setattr(
        "ui.app.review_closed_trades",
        lambda **kwargs: captured.update(kwargs) or {
            "ok": True,
            "reviewed_count": 1,
            "skipped_count": 0,
            "reviews": [{"recommendation_id": 1}],
            "errors": [],
        },
    )

    response = client.post("/journal/review-closed-trades", json={"store_memory": True})

    assert response.status_code == 200
    assert response.json()["reviewed_count"] == 1
    assert captured["store_memory"] is True


@pytest.mark.skipif(not UI_ROUTE_TEST_DEPS_AVAILABLE, reason="fastapi/httpx is not installed in the local test environment.")
def test_journal_reviews_route_returns_reviews(monkeypatch):
    captured = {}
    monkeypatch.setattr(
        "ui.app.get_trade_reviews",
        lambda **kwargs: captured.update(kwargs) or {
            "ok": True,
            "count": 1,
            "reviews": [{"recommendation_id": kwargs["recommendation_id"], "ticker": kwargs["ticker"]}],
            "error": None,
        },
    )

    response = client.get("/journal/reviews?recommendation_id=1&ticker=AAPL")

    assert response.status_code == 200
    assert response.json()["count"] == 1
    assert captured["recommendation_id"] == 1
    assert captured["ticker"] == "AAPL"


@pytest.mark.skipif(not UI_ROUTE_TEST_DEPS_AVAILABLE, reason="fastapi/httpx is not installed in the local test environment.")
def test_api_chat_route_returns_structured_assistant_response(monkeypatch):
    captured = {}
    monkeypatch.setattr("ui.app.get_model_init_error", lambda: "GEMINI_API_KEY is not configured.")
    monkeypatch.setattr("ui.app.execute_scan_plan", _fake_planned_execution(captured, ticker="AAPL"))

    response = client.post("/api/chat", json={"message": "Review AAPL"})

    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is True
    assert payload["paper_trading_only"] is True
    assert payload["validation"]["deterministic_engine_source_of_truth"] is True
    assert payload["planner"]["intent"]["objective"] == "ticker_review"
    assert captured["proposed_plan"]["custom_tickers"] == ["AAPL"]
    assert captured["internal_controls"]["scan_total_timeout_seconds"] <= 45.0
    assert "use_dynamic_discovery" not in captured["internal_controls"]
    assert payload["discovery_summary"]["discovery_used"] is False
    assert payload["discovery_summary"]["bypass_reason"] == "explicit_ticker_scope"
    assert payload["assistant_response"]["market_state"]["discovery_used"] is False


@pytest.mark.skipif(not UI_ROUTE_TEST_DEPS_AVAILABLE, reason="fastapi/httpx is not installed in the local test environment.")
def test_api_chat_review_timeout_returns_ranking_unavailable(monkeypatch):
    captured = {}
    monkeypatch.setenv("CHAT_SCAN_TIMEOUT_SECONDS", "0.01")
    monkeypatch.setattr("ui.app.get_model_init_error", lambda: "GEMINI_API_KEY is not configured.")

    def hanging_execute_scan_plan(proposed_plan, runtime_context=None, db_path="strategy_library.db", internal_controls=None):
        captured["proposed_plan"] = dict(proposed_plan or {})
        captured["internal_controls"] = dict(internal_controls or {})
        time.sleep(0.2)
        return {"ok": True, "best_available_ideas": {"paper_eligible": [{"ticker": "AAPL"}]}}

    monkeypatch.setattr("ui.app.execute_scan_plan", hanging_execute_scan_plan)

    response = client.post("/api/chat", json={"message": "Review AAPL"})
    payload = response.json()
    deadline = time.time() + 1.0
    while "internal_controls" not in captured and time.time() < deadline:
        time.sleep(0.01)

    assert response.status_code == 200
    assert payload["ok"] is True
    assert payload["mode"] == "deterministic_timeout"
    assert payload["ranking_status"] == "ranking_unavailable"
    assert payload["assistant_response"]["status"] == "ranking_unavailable"
    assert payload["assistant_response"]["top_stocks"] == []
    assert payload["assistant_response"]["top_options"] == []
    assert payload["assistant_response"]["ticker_cards"] == []
    assert payload["best_available_ideas"]["paper_eligible"] == []
    assert payload["best_available_ideas"]["stock_watchlist"] == []
    assert payload["best_available_ideas"]["blocked_but_interesting"] == []
    assert "Market data provider timed out" in payload["answer"]
    assert any("IBKR/TWS" in warning for warning in payload["warnings"])
    assert payload["validation"]["paper_trade_logged"] is False
    assert payload["brokerage_execution_enabled"] is False
    assert captured["internal_controls"]["scan_total_timeout_seconds"] <= 0.01


@pytest.mark.skipif(not UI_ROUTE_TEST_DEPS_AVAILABLE, reason="fastapi/httpx is not installed in the local test environment.")
def test_api_chat_broad_scan_timeout_returns_ranking_unavailable(monkeypatch):
    monkeypatch.setenv("CHAT_SCAN_TIMEOUT_SECONDS", "0.01")
    monkeypatch.setattr("ui.app.get_model_init_error", lambda: "GEMINI_API_KEY is not configured.")

    def hanging_adaptive_scan(*args, **kwargs):
        time.sleep(0.2)
        return {"ok": True, "best_available_ideas": {"stock_watchlist": [{"ticker": "AAPL"}]}}

    monkeypatch.setattr("ui.app.execute_adaptive_scan_plan", hanging_adaptive_scan)

    response = client.post("/api/chat", json={"message": "Give me your best stocks right now. Do stock only."})
    payload = response.json()

    assert response.status_code == 200
    assert payload["ok"] is True
    assert payload["ranking_status"] == "ranking_unavailable"
    assert payload["assistant_response"]["top_stocks"] == []
    assert payload["assistant_response"]["ticker_cards"] == []
    assert payload["best_available_ideas"]["stock_watchlist"] == []
    assert "Market ranking is unavailable" in payload["answer"]
    assert "AAPL" not in payload["answer"]
    assert payload["raw_result"]["include_options"] is False
    assert payload["scan_result"]["status"] == "timeout"


@pytest.mark.skipif(not UI_ROUTE_TEST_DEPS_AVAILABLE, reason="fastapi/httpx is not installed in the local test environment.")
def test_api_chat_returns_deterministic_fallback_when_gemini_unavailable(monkeypatch):
    captured = {}
    monkeypatch.setattr(
        "ui.app.ask_translator",
        lambda message: "Sorry, the AI translator is unavailable right now because the Gemini runtime is not fully configured.",
    )
    monkeypatch.setattr("ui.app.get_model_init_error", lambda: "GEMINI_API_KEY is not configured.")
    monkeypatch.setattr("ui.app.execute_adaptive_scan_plan", _fake_adaptive_execution(captured, ticker="AAPL"))

    response = client.post("/api/chat", json={"message": "Find the best trades this week"})

    payload = response.json()
    assert response.status_code == 200
    assert payload["ok"] is True
    assert payload["mode"] == "deterministic_fallback"
    assert payload["gemini_available"] is False
    assert payload["best_available_ideas"]["stock_watchlist"][0]["ticker"] == "AAPL"
    assert payload["assistant_response"]["response_type"] == "trade_ideas"
    assert payload["assistant_response"]["top_stocks"][0]["ticker"] == "AAPL"
    assert payload["policy_validation"]["policy_version"] == "scan_policy_v1"
    assert payload["planner"]["planner_version"] == "ai_scan_planner_v1"
    assert payload["planner_status"] == "deterministic_planned"
    assert payload["planner_provider"] == "deterministic"
    assert payload["planner_fallback_used"] is False
    assert payload["approved_plan"]["universes"] == ["large_cap", "active", "tech"]
    assert captured["proposed_plan"]["universes"] == ["large_cap", "active", "tech"]
    assert captured["include_options"] is False


@pytest.mark.skipif(not UI_ROUTE_TEST_DEPS_AVAILABLE, reason="fastapi/httpx is not installed in the local test environment.")
def test_api_chat_stock_only_request_sends_include_options_false(monkeypatch):
    captured = {}
    monkeypatch.setattr("ui.app.get_model_init_error", lambda: "GEMINI_API_KEY is not configured.")
    monkeypatch.setattr("ui.app.execute_adaptive_scan_plan", _fake_adaptive_execution(captured, ticker="NVDA"))

    response = client.post("/api/chat", json={"message": "Give me your best stock ideas right now. Do stock only. Do not include options."})

    payload = response.json()
    assert response.status_code == 200
    assert payload["ok"] is True
    assert captured["include_options"] is False
    assert captured["prefer_options"] is False
    assert payload["raw_result"]["include_options"] is False
    assert payload["raw_result"]["planner_status"] == "deterministic_planned"
    assert payload["best_available_ideas"]["option_research_only"] == []
    assert payload["assistant_response"]["requested_instrument"] == "stocks"
    assert payload["assistant_response"]["top_options"] == []
    assert "There is no current event loop" not in str(payload)


@pytest.mark.skipif(not UI_ROUTE_TEST_DEPS_AVAILABLE, reason="fastapi/httpx is not installed in the local test environment.")
@pytest.mark.parametrize(
    "message",
    [
        "Give me your best available stock ideas right now. Do stock only. Include watchlist and blocked-but-interesting ideas, but do not include options.",
        "Show me stock ideas right now. No options.",
        "What stocks to watch today? Equities only.",
        "Include watchlist ideas and blocked but interesting stock setups, no options.",
    ],
)
def test_api_chat_best_available_stock_ideas_trigger_deterministic_scan(monkeypatch, message):
    captured = {}
    monkeypatch.setattr("ui.app.get_model_init_error", lambda: "GEMINI_API_KEY is not configured.")
    monkeypatch.setattr("ui.app.execute_adaptive_scan_plan", _fake_adaptive_execution(captured, ticker="V"))

    response = client.post("/api/chat", json={"message": message})

    payload = response.json()
    assert response.status_code == 200
    assert payload["ok"] is True
    assert payload["mode"] == "deterministic_fallback"
    assert captured["include_options"] is False
    assert captured["prefer_options"] is False
    assert payload["raw_result"]["include_options"] is False
    assert payload["best_available_ideas"]["stock_watchlist"][0]["ticker"] == "V"
    assert payload["best_available_ideas"]["option_research_only"] == []
    assert payload["assistant_response"]["top_stocks"][0]["ticker"] == "V"
    assert payload["assistant_response"]["top_options"] == []
    assert "Use the Scan, Trades, Performance" not in payload["answer"]
    assert payload["planner_status"] == "deterministic_planned"


@pytest.mark.skipif(not UI_ROUTE_TEST_DEPS_AVAILABLE, reason="fastapi/httpx is not installed in the local test environment.")
def test_api_chat_broad_stock_scan_uses_bounded_chat_controls(monkeypatch):
    captured = {}
    monkeypatch.setenv("CHAT_BROAD_SCAN_MAX_TICKERS", "7")
    monkeypatch.setenv("CHAT_BROAD_SCAN_MAX_CANDIDATES", "6")
    monkeypatch.setattr("ui.app.get_model_init_error", lambda: "GEMINI_API_KEY is not configured.")
    monkeypatch.setattr("ui.app.execute_adaptive_scan_plan", _fake_adaptive_execution(captured, ticker="MSFT"))

    response = client.post("/api/chat", json={"message": "Give me your best stocks"})

    payload = response.json()
    assert response.status_code == 200
    assert payload["ok"] is True
    assert captured["proposed_plan"]["max_tickers"] == 7
    assert captured["proposed_plan"]["max_candidates"] == 6
    assert captured["internal_controls"]["chat_broad_scan"] is True
    assert captured["internal_controls"]["bounded_first_batch"] is True
    assert captured["internal_controls"]["stop_after_first_legitimate_pass"] is True
    assert captured["internal_controls"]["use_dynamic_discovery"] is True
    assert captured["internal_controls"]["max_discovered_tickers"] == 7
    assert captured["internal_controls"]["discovery_sources"] == ["manual_hotlist", "database_recent", "liquid_fallback"]
    assert captured["internal_controls"]["scan_total_timeout_seconds"] < 45.0
    assert captured["include_options"] is False
    assert payload["discovery_summary"]["discovery_used"] is True
    assert payload["discovery_summary"]["discovered_count"] == 2
    assert payload["assistant_response"]["market_state"]["sources_used"] == ["manual_hotlist"]
    assert payload["provider_capabilities"][0]["provider_name"] == "test_market_data"
    assert payload["execution_summary"]["provider_capabilities"][0]["available"] is True
    assert payload["assistant_response"]["market_state"]["provider_capabilities"][0]["provider_type"] == "market_data"
    assert payload["brokerage_execution_enabled"] is False
    assert payload["paper_trading_only"] is True
    assert POLICY_LIMITS["max_tickers"]["max"] == 500
    assert POLICY_LIMITS["max_candidates"]["max"] == 100


@pytest.mark.skipif(not UI_ROUTE_TEST_DEPS_AVAILABLE, reason="fastapi/httpx is not installed in the local test environment.")
def test_api_chat_broad_stock_scan_defaults_fit_bridge_timeout(monkeypatch):
    captured = {}
    monkeypatch.delenv("CHAT_BROAD_SCAN_MAX_TICKERS", raising=False)
    monkeypatch.delenv("CHAT_BROAD_SCAN_MAX_CANDIDATES", raising=False)
    monkeypatch.delenv("CHAT_SCAN_TOTAL_TIMEOUT_SECONDS", raising=False)
    monkeypatch.delenv("CHAT_SCAN_TICKER_TIMEOUT_SECONDS", raising=False)
    monkeypatch.setattr("ui.app.get_model_init_error", lambda: "GEMINI_API_KEY is not configured.")
    monkeypatch.setattr("ui.app.execute_adaptive_scan_plan", _fake_adaptive_execution(captured, ticker="MSFT"))

    response = client.post("/api/chat", json={"message": "Give me your best stocks"})

    assert response.status_code == 200
    assert captured["proposed_plan"]["max_tickers"] == 6
    assert captured["proposed_plan"]["max_candidates"] == 6
    assert captured["internal_controls"]["use_dynamic_discovery"] is True
    assert captured["internal_controls"]["max_discovered_tickers"] == 6
    assert response.json()["discovery_summary"]["discovery_used"] is True
    assert captured["internal_controls"]["scan_total_timeout_seconds"] <= 9.0
    assert captured["internal_controls"]["scan_ticker_timeout_seconds"] <= 4.0
    assert captured["internal_controls"]["scan_total_timeout_seconds"] < 45.0
    assert response.json()["brokerage_execution_enabled"] is False


@pytest.mark.skipif(not UI_ROUTE_TEST_DEPS_AVAILABLE, reason="fastapi/httpx is not installed in the local test environment.")
def test_api_chat_options_request_can_send_include_options_true(monkeypatch):
    captured = {}
    monkeypatch.setattr("ui.app.get_model_init_error", lambda: "GEMINI_API_KEY is not configured.")
    monkeypatch.setattr("ui.app.execute_adaptive_scan_plan", _fake_adaptive_execution(captured, ticker="AAPL", include_options=True))

    response = client.post("/api/chat", json={"message": "Give me the best option ideas"})

    assert response.status_code == 200
    assert captured["include_options"] is True
    assert captured["prefer_options"] is True


@pytest.mark.skipif(not UI_ROUTE_TEST_DEPS_AVAILABLE, reason="fastapi/httpx is not installed in the local test environment.")
def test_api_chat_current_news_sets_research_preferences(monkeypatch):
    captured = {}
    monkeypatch.setattr("ui.app.get_model_init_error", lambda: "GEMINI_API_KEY is not configured.")
    monkeypatch.setattr("ui.app.execute_adaptive_scan_plan", _fake_adaptive_execution(captured, ticker="AAPL"))

    response = client.post("/api/chat", json={"message": "Give me the best stocks and check current news. Do stock only."})

    payload = response.json()
    assert response.status_code == 200
    assert payload["ok"] is True
    assert captured["proposed_plan"]["research_preferences"]["include_news"] is True
    assert captured["include_options"] is False


@pytest.mark.skipif(not UI_ROUTE_TEST_DEPS_AVAILABLE, reason="fastapi/httpx is not installed in the local test environment.")
def test_api_chat_status_question_does_not_execute_scan(monkeypatch):
    def forbidden_scan(*args, **kwargs):
        raise AssertionError("Status chat must not execute a market scan.")

    monkeypatch.setattr("ui.app.execute_scan_plan", forbidden_scan)
    monkeypatch.setattr("ui.app.execute_adaptive_scan_plan", forbidden_scan)
    monkeypatch.setattr("ui.app.check_runtime_readiness", lambda config=None, include_live_checks=False: {"ok": True, "categories": {}, "warnings": [], "errors": []})
    monkeypatch.setattr("ui.app.get_paper_trading_summary", lambda db_path="strategy_library.db": {"ok": True, "summary": {}})
    monkeypatch.setattr("ui.app.list_alerts", lambda **kwargs: {"ok": True, "alerts": []})
    monkeypatch.setattr("ui.app.get_win_loss_record", lambda db_path="strategy_library.db": {"ok": True})
    monkeypatch.setattr("ui.app.get_strategy_performance", lambda db_path="strategy_library.db": {"ok": True})
    monkeypatch.setattr("ui.app.validate_schema", lambda db_path="strategy_library.db": {"ok": True, "errors": []})
    monkeypatch.setattr("ui.app.get_model_init_error", lambda: "GEMINI_API_KEY is not configured.")

    response = client.post("/api/chat", json={"message": "What is the system status?"})

    payload = response.json()
    assert response.status_code == 200
    assert payload["ok"] is True
    assert payload["mode"] == "deterministic_status"
    assert payload["status_payload"]["ok"] is True
    assert "scan was run" in payload["answer"]


@pytest.mark.skipif(not UI_ROUTE_TEST_DEPS_AVAILABLE, reason="fastapi/httpx is not installed in the local test environment.")
def test_api_scan_includes_best_available_ideas(monkeypatch):
    captured = {}

    def fake_run_paper_trade_cycle(**kwargs):
        asyncio.get_event_loop()
        captured.update(kwargs)
        return {
            "ok": True,
            "mode": "paper_trading",
            "decision_result": {"final_recommendations": []},
            "selection_result": {
                "watchlist_alternatives": [
                    {"ticker": "MSFT", "asset_type": "stock", "recommendation_status": "watchlist", "score": 81, "risk_reward": 2.3}
                ]
            },
            "summary": {"selected_count": 0, "logged_count": 0},
            "errors": [],
        }

    monkeypatch.setattr(
        "ui.app.run_paper_trade_cycle",
        fake_run_paper_trade_cycle,
    )

    response = client.post("/api/scan", json={"max_tickers": 5, "min_trades": 0})

    payload = response.json()
    assert response.status_code == 200
    assert payload["ok"] is True
    assert payload["best_available_ideas"]["stock_watchlist"][0]["ticker"] == "MSFT"
    assert payload["assistant_response"]["response_type"] == "trade_ideas"
    assert payload["assistant_response"]["top_stocks"][0]["ticker"] == "MSFT"
    assert "No final paper trades" in payload["formatted_best_ideas_summary"]
    assert captured["include_options"] is False
    assert captured["prefer_options"] is False
    assert "There is no current event loop" not in str(payload)


@pytest.mark.skipif(not UI_ROUTE_TEST_DEPS_AVAILABLE, reason="fastapi/httpx is not installed in the local test environment.")
def test_api_trades_route_returns_trade_history(monkeypatch):
    monkeypatch.setattr("ui.app.get_trade_history", lambda db_path="strategy_library.db": [{"id": 1, "ticker": "AAPL"}])

    response = client.get("/api/trades")

    assert response.status_code == 200
    assert response.json()["ok"] is True
    assert response.json()["trades"][0]["ticker"] == "AAPL"


@pytest.mark.skipif(not UI_ROUTE_TEST_DEPS_AVAILABLE, reason="fastapi/httpx is not installed in the local test_environment.")
def test_api_trade_detail_route_returns_recommendation(monkeypatch):
    monkeypatch.setattr("ui.app.get_recommendation", lambda recommendation_id, db_path="strategy_library.db": {"id": recommendation_id, "ticker": "AAPL"})
    monkeypatch.setattr("ui.app.get_trade_reviews", lambda **kwargs: {"ok": True, "reviews": []})

    response = client.get("/api/trades/1")

    assert response.status_code == 200
    assert response.json()["trade"]["id"] == 1


@pytest.mark.skipif(not UI_ROUTE_TEST_DEPS_AVAILABLE, reason="fastapi/httpx is not installed in the local test environment.")
def test_api_options_strategies_route_uses_backend_builder(monkeypatch):
    monkeypatch.setattr("ui.app.get_market_snapshot", lambda ticker, lookback_days=180: {"ok": True, "data": {"technical_snapshot": {"current_price": 100}}})
    monkeypatch.setattr("ui.app.get_options_chain", lambda ticker: {"ok": True, "data": {"contracts": [{"option_contract": "AAPL260717C00100000"}]}})
    monkeypatch.setattr(
        "ui.app.build_option_strategy_candidates",
        lambda ticker, view, contracts: {
            "ok": True,
            "ticker": ticker,
            "strategies": [{"strategy_type": "long_call", "status": "research_only"}],
            "summary": {"research_only_count": 1},
            "warnings": [],
            "errors": [],
        },
    )

    response = client.post("/api/options/strategies", json={"ticker": "AAPL"})

    assert response.status_code == 200
    assert response.json()["ok"] is True
    assert response.json()["strategy_result"]["strategies"][0]["status"] == "research_only"


@pytest.mark.skipif(not UI_ROUTE_TEST_DEPS_AVAILABLE, reason="fastapi/httpx is not installed in the local test environment.")
def test_api_options_strategies_returns_blocked_payload_when_chain_unavailable(monkeypatch):
    monkeypatch.setattr("ui.app.get_market_snapshot", lambda ticker, lookback_days=180: {"ok": True, "data": {"technical_snapshot": {"current_price": 100}}})
    monkeypatch.setattr("ui.app.get_options_chain", lambda ticker: {"ok": False, "data": {"contracts": []}, "error": "IBKR option quotes unavailable: OPRA permission missing."})
    monkeypatch.setattr(
        "ui.app.build_option_strategy_candidates",
        lambda ticker, view, contracts: {
            "ok": False,
            "ticker": ticker,
            "strategies": [],
            "summary": {"blocked_count": 0},
            "warnings": ["Option chain is empty or malformed."],
            "errors": ["Option chain is empty or malformed."],
        },
    )

    response = client.post("/api/options/strategies", json={"ticker": "AAPL"})

    payload = response.json()
    assert response.status_code == 200
    assert payload["ok"] is False
    assert "Cannot run the event loop" not in str(payload)
    assert payload["paper_trading_only"] is True
    assert "OPRA permission" in payload["warnings"][-1]


@pytest.mark.skipif(not UI_ROUTE_TEST_DEPS_AVAILABLE, reason="fastapi/httpx is not installed in the local test environment.")
def test_api_options_discover_route_is_research_only_and_validates_tickers(monkeypatch):
    captured = {}

    def fake_discover(stock_candidates, explicit_tickers=None, option_preferences=None, runtime_context=None, max_underlyings=5, max_contracts_per_ticker=3):
        captured.update(
            {
                "stock_candidates": stock_candidates,
                "explicit_tickers": explicit_tickers,
                "option_preferences": option_preferences,
                "runtime_context": runtime_context,
                "max_underlyings": max_underlyings,
                "max_contracts_per_ticker": max_contracts_per_ticker,
            }
        )
        return {
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
            "underlying_watchlist": [{"ticker": "AAPL"}],
            "missing_requirements": ["bid/ask"],
            "warnings": [],
            "errors": [],
        }

    monkeypatch.setattr("ui.app.discover_option_ideas", fake_discover)

    response = client.post(
        "/api/options/discover",
        json={
            "tickers": ["AAPL"],
            "option_preferences": {"min_dte": 14, "max_dte": 45},
            "runtime_context": {"safe_to_run_options": False},
            "max_underlyings": 1,
            "max_contracts_per_ticker": 2,
        },
    )

    payload = response.json()
    assert response.status_code == 200
    assert payload["status"] == "partial"
    assert payload["paper_trading_only"] is True
    assert payload["brokerage_execution_enabled"] is False
    assert captured["explicit_tickers"] == ["AAPL"]
    assert captured["runtime_context"]["requested"] is True
    assert captured["max_contracts_per_ticker"] == 2


@pytest.mark.skipif(not UI_ROUTE_TEST_DEPS_AVAILABLE, reason="fastapi/httpx is not installed in the local test environment.")
def test_api_annotation_route_saves_human_annotation(monkeypatch):
    captured = {}
    monkeypatch.setattr(
        "ui.app.add_human_annotation",
        lambda **kwargs: captured.update(kwargs) or {"ok": True, "annotation": {"ticker": kwargs["ticker"]}, "error": None},
    )

    response = client.post("/api/annotations", json={"ticker": "AAPL", "notes": "Good process"})

    assert response.status_code == 200
    assert response.json()["annotation"]["ticker"] == "AAPL"
    assert captured["notes"] == "Good process"


@pytest.mark.skipif(not UI_ROUTE_TEST_DEPS_AVAILABLE, reason="fastapi/httpx is not installed in the local test environment.")
def test_api_system_routes_return_structured_payloads(monkeypatch):
    monkeypatch.setattr("ui.app.validate_startup_config", lambda config=None: {"ok": True, "checks": [], "warnings": [], "errors": []})
    monkeypatch.setattr("ui.app.check_runtime_readiness", lambda config=None, include_live_checks=False: {"ok": True, "categories": {}, "warnings": [], "errors": []})
    monkeypatch.setattr("ui.app.run_provider_dry_run", lambda **kwargs: {"ok": True, "checks": {}, "warnings": [], "errors": []})

    assert client.post("/api/system/config-check", json={}).json()["ok"] is True
    assert client.post("/api/system/readiness-check", json={}).json()["ok"] is True
    assert client.post("/api/system/live-dry-run", json={"ticker": "AAPL"}).json()["ok"] is True


@pytest.mark.skipif(not UI_ROUTE_TEST_DEPS_AVAILABLE, reason="fastapi/httpx is not installed in the local test environment.")
def test_api_status_and_frontend_debug_are_safe(monkeypatch):
    monkeypatch.setattr("ui.app.check_runtime_readiness", lambda config=None, include_live_checks=False: {"ok": True, "categories": {}, "warnings": [], "errors": []})
    monkeypatch.setattr("ui.app.get_paper_trading_summary", lambda db_path="strategy_library.db": {"ok": True, "summary": {}})
    monkeypatch.setattr("ui.app.list_alerts", lambda **kwargs: {"ok": True, "alerts": []})
    monkeypatch.setattr("ui.app.get_win_loss_record", lambda db_path="strategy_library.db": {"ok": True})
    monkeypatch.setattr("ui.app.get_strategy_performance", lambda db_path="strategy_library.db": {"ok": True})
    monkeypatch.setattr("ui.app.validate_schema", lambda db_path="strategy_library.db": {"ok": True, "errors": []})
    monkeypatch.setattr("ui.app.get_model_init_error", lambda: "GEMINI_API_KEY is not configured.")

    status = client.get("/api/status").json()
    debug = client.get("/api/frontend-debug").json()

    assert status["ok"] is True
    assert status["backend"] == "running"
    assert status["brokerage_execution_enabled"] is False
    assert status["frontend_bridge"] == "ready"
    assert status["ai_planner_provider"] == "deterministic"
    assert status["ai_planner_available"] is False
    assert "openai_planner_model" in status
    assert "ai_research_provider" in status
    assert "openai_research_configured" in status
    assert "research_max_tickers" in status
    assert debug["ok"] is True
    assert debug["secrets_exposed"] is False
    assert "GEMINI_API_KEY" not in str(debug)


def test_chat_frontend_renders_clickable_sources_safely():
    source = open("/Users/kevinfrederick/trading_ai/frontend/components/ideas/ResearchSources.tsx", encoding="utf-8").read()
    normalizer = open("/Users/kevinfrederick/trading_ai/frontend/lib/tradingTypes.ts", encoding="utf-8").read()

    assert 'target="_blank"' in source
    assert 'rel="noopener noreferrer"' in source
    assert "dangerouslySetInnerHTML" not in source
    assert "safeHttpUrl" in source
    assert 'url.protocol === "http:" || url.protocol === "https:"' in normalizer
