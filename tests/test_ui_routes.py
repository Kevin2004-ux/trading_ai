import importlib.util

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
