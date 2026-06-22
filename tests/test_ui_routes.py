import importlib.util
import asyncio

import pytest


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
    assert "/api/chat" in route_paths
    assert "/api/scan" in route_paths
    assert "/api/options/strategies" in route_paths
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
    monkeypatch.setattr("ui.app.ask_translator", lambda message: f"answer: {message}")

    response = client.post("/api/chat", json={"message": "Review AAPL"})

    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is True
    assert payload["paper_trading_only"] is True
    assert payload["validation"]["deterministic_engine_source_of_truth"] is True


@pytest.mark.skipif(not UI_ROUTE_TEST_DEPS_AVAILABLE, reason="fastapi/httpx is not installed in the local test environment.")
def test_api_chat_returns_deterministic_fallback_when_gemini_unavailable(monkeypatch):
    captured = {}
    monkeypatch.setattr(
        "ui.app.ask_translator",
        lambda message: "Sorry, the AI translator is unavailable right now because the Gemini runtime is not fully configured.",
    )
    monkeypatch.setattr("ui.app.get_model_init_error", lambda: "GEMINI_API_KEY is not configured.")
    monkeypatch.setattr(
        "ui.app.run_paper_trade_cycle",
        lambda **kwargs: captured.update(kwargs) or {
            "ok": True,
            "mode": "paper_trading",
            "decision_result": {"final_recommendations": []},
            "selection_result": {
                "watchlist_alternatives": [
                    {"ticker": "AAPL", "asset_type": "stock", "recommendation_status": "watchlist", "score": 80, "risk_reward": 2.2}
                ]
            },
            "summary": {"selected_count": 0, "logged_count": 0},
            "errors": [],
        },
    )

    response = client.post("/api/chat", json={"message": "Find the best trades this week"})

    payload = response.json()
    assert response.status_code == 200
    assert payload["ok"] is True
    assert payload["mode"] == "deterministic_fallback"
    assert payload["gemini_available"] is False
    assert payload["best_available_ideas"]["stock_watchlist"][0]["ticker"] == "AAPL"
    assert captured["min_trades"] == 0
    assert captured["include_options"] is False


@pytest.mark.skipif(not UI_ROUTE_TEST_DEPS_AVAILABLE, reason="fastapi/httpx is not installed in the local test environment.")
def test_api_chat_stock_only_request_sends_include_options_false(monkeypatch):
    captured = {}
    monkeypatch.setattr("ui.app.get_model_init_error", lambda: "GEMINI_API_KEY is not configured.")

    def fake_run_paper_trade_cycle(**kwargs):
        asyncio.get_event_loop()
        captured.update(kwargs)
        return {
            "ok": True,
            "mode": "paper_trading",
            "decision_result": {"final_recommendations": []},
            "selection_result": {
                "watchlist_alternatives": [
                    {"ticker": "NVDA", "asset_type": "stock", "recommendation_status": "watchlist", "score": 79}
                ]
            },
            "summary": {"selected_count": 0, "logged_count": 0},
            "errors": [],
        }

    monkeypatch.setattr(
        "ui.app.run_paper_trade_cycle",
        fake_run_paper_trade_cycle,
    )

    response = client.post("/api/chat", json={"message": "Give me your best stock ideas right now. Do stock only. Do not include options."})

    payload = response.json()
    assert response.status_code == 200
    assert payload["ok"] is True
    assert captured["include_options"] is False
    assert captured["prefer_options"] is False
    assert payload["raw_result"]["include_options"] is False
    assert payload["best_available_ideas"]["option_research_only"] == []
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

    def fake_run_paper_trade_cycle(**kwargs):
        asyncio.get_event_loop()
        captured.update(kwargs)
        return {
            "ok": True,
            "mode": "paper_trading",
            "decision_result": {"final_recommendations": []},
            "selection_result": {
                "watchlist_alternatives": [
                    {"ticker": "V", "asset_type": "stock", "recommendation_status": "watchlist", "score": 88, "risk_reward": 2.0}
                ],
                "rejected_candidates": [
                    {"ticker": "AAPL", "asset_type": "stock", "recommendation_status": "rejected", "score": 77, "rejection_reason": "Failed relative volume."}
                ],
            },
            "summary": {"selected_count": 0, "logged_count": 0},
            "errors": [],
        }

    monkeypatch.setattr("ui.app.run_paper_trade_cycle", fake_run_paper_trade_cycle)

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
    assert "Use the Scan, Trades, Performance" not in payload["answer"]


@pytest.mark.skipif(not UI_ROUTE_TEST_DEPS_AVAILABLE, reason="fastapi/httpx is not installed in the local test environment.")
def test_api_chat_options_request_can_send_include_options_true(monkeypatch):
    captured = {}
    monkeypatch.setattr("ui.app.get_model_init_error", lambda: "GEMINI_API_KEY is not configured.")
    monkeypatch.setattr(
        "ui.app.run_paper_trade_cycle",
        lambda **kwargs: captured.update(kwargs) or {
            "ok": True,
            "mode": "paper_trading",
            "decision_result": {"final_recommendations": []},
            "selection_result": {"watchlist_alternatives": []},
            "summary": {"selected_count": 0, "logged_count": 0},
            "errors": [],
        },
    )

    response = client.post("/api/chat", json={"message": "Give me the best option ideas"})

    assert response.status_code == 200
    assert captured["include_options"] is True
    assert captured["prefer_options"] is False


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
    assert debug["ok"] is True
    assert debug["secrets_exposed"] is False
    assert "GEMINI_API_KEY" not in str(debug)
