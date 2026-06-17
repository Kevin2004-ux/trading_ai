from contextlib import redirect_stdout
from io import StringIO
import json

import cli


def _run_cli_and_capture(argv: list[str]) -> tuple[int, str]:
    stdout = StringIO()
    with redirect_stdout(stdout):
        exit_code = cli.main(argv)
    return exit_code, stdout.getvalue()


def test_cli_paper_cycle_prints_json_and_exits_zero(monkeypatch):
    captured = {}

    monkeypatch.setattr(
        "cli.run_weekly_paper_cycle_job",
        lambda **kwargs: captured.update(kwargs) or {
            "ok": True,
            "job": "weekly_paper_cycle",
            "mode": "paper_trading",
            "warning": "simulated only",
            "errors": [],
        },
    )

    exit_code, output = _run_cli_and_capture(
        [
            "paper-cycle",
            "--no-include-market-regime",
            "--no-include-relative-strength",
            "--include-options",
            "--prefer-options",
            "--max-option-contracts-per-trade",
            "2",
            "--no-include-portfolio-risk",
            "--no-include-position-sizing",
            "--no-include-memory-context",
            "--store-memory",
            "--account-size",
            "25000",
            "--risk-mode",
            "conservative",
            "--scan-max-concurrency",
            "4",
            "--scan-ticker-timeout-seconds",
            "9",
            "--scan-total-timeout-seconds",
            "45",
            "--disable-async-scan",
        ]
    )
    output = output.strip()
    payload = json.loads(output)

    assert exit_code == 0
    assert payload["ok"] is True
    assert payload["job"] == "weekly_paper_cycle"
    assert captured["include_market_regime"] is False
    assert captured["include_relative_strength"] is False
    assert captured["include_options"] is True
    assert captured["prefer_options"] is True
    assert captured["max_option_contracts_per_trade"] == 2
    assert captured["include_portfolio_risk"] is False
    assert captured["include_position_sizing"] is False
    assert captured["include_memory_context"] is False
    assert captured["store_memory"] is True
    assert captured["account_size"] == 25000.0
    assert captured["risk_mode"] == "conservative"
    assert captured["scan_max_concurrency"] == 4
    assert captured["scan_ticker_timeout_seconds"] == 9.0
    assert captured["scan_total_timeout_seconds"] == 45.0
    assert captured["use_async_scan"] is False


def test_cli_paper_review_prints_json_and_exits_zero(monkeypatch):
    captured = {}

    monkeypatch.setattr(
        "cli.run_daily_paper_review_job",
        lambda **kwargs: captured.update(kwargs) or {
            "ok": True,
            "job": "daily_paper_review",
            "mode": "paper_trading",
            "warning": "simulated only",
            "errors": [],
        },
    )

    exit_code, output = _run_cli_and_capture(
        [
            "paper-review",
            "--no-include-trade-reviews",
            "--store-review-memory",
        ]
    )
    output = output.strip()
    payload = json.loads(output)

    assert exit_code == 0
    assert payload["ok"] is True
    assert payload["job"] == "daily_paper_review"
    assert captured["include_trade_reviews"] is False
    assert captured["store_review_memory"] is True


def test_cli_paper_summary_prints_json_and_exits_zero(monkeypatch):
    monkeypatch.setattr(
        "cli.run_paper_summary_job",
        lambda **kwargs: {
            "ok": True,
            "job": "paper_summary",
            "mode": "paper_trading",
            "warning": "simulated only",
            "errors": [],
        },
    )

    exit_code, output = _run_cli_and_capture(["paper-summary"])
    output = output.strip()
    payload = json.loads(output)

    assert exit_code == 0
    assert payload["ok"] is True
    assert payload["job"] == "paper_summary"


def test_cli_stress_scenarios_prints_json():
    exit_code, output = _run_cli_and_capture(["stress-scenarios"])
    payload = json.loads(output)

    assert exit_code == 0
    assert payload["ok"] is True
    assert payload["scenario_count"] >= 18


def test_cli_stress_test_runs_named_scenario():
    exit_code, output = _run_cli_and_capture(["stress-test", "--scenario", "market_gap_down"])
    payload = json.loads(output)

    assert exit_code == 0
    assert payload["ok"] is True
    assert payload["scenario_name"] == "market_gap_down"


def test_cli_stress_suite_runs_default_suite():
    exit_code, output = _run_cli_and_capture(["stress-suite"])
    payload = json.loads(output)

    assert exit_code == 0
    assert payload["ok"] is True
    assert payload["mode"] == "stress_test"


def test_cli_portfolio_stress_runs_against_temp_db(tmp_path):
    db_path = tmp_path / "portfolio_stress.db"
    exit_code, output = _run_cli_and_capture(
        ["portfolio-stress", "--scenario", "volatility_spike", "--db-path", str(db_path)]
    )
    payload = json.loads(output)

    assert exit_code == 0
    assert payload["ok"] is True
    assert payload["open_trade_count"] == 0


def test_cli_data_failure_sim_runs_provider_outage():
    exit_code, output = _run_cli_and_capture(["data-failure-sim", "--scenario", "provider_outage"])
    payload = json.loads(output)

    assert exit_code == 0
    assert payload["ok"] is True
    assert payload["data_quality"]["final_recommendation_allowed"] is False


def test_cli_research_brief_prints_json_and_exits_zero(monkeypatch):
    captured = {}

    monkeypatch.setattr(
        "cli.get_deep_research_brief_tool",
        lambda **kwargs: captured.update(kwargs) or {
            "ok": True,
            "tool": "get_deep_research_brief_tool",
            "timestamp": "2026-06-07T00:00:00+00:00",
            "data": {
                "ticker": kwargs["ticker"],
                "brief_type": "deep_research",
            },
            "error": None,
        },
    )

    exit_code, output = _run_cli_and_capture(
        [
            "research-brief",
            "--ticker",
            "AAPL",
            "--no-include-sec-filings",
            "--no-include-earnings-transcripts",
            "--include-options",
            "--pretty",
        ]
    )
    payload = json.loads(output)

    assert exit_code == 0
    assert payload["ok"] is True
    assert payload["tool"] == "get_deep_research_brief_tool"
    assert captured["ticker"] == "AAPL"
    assert captured["include_sec_filings"] is False
    assert captured["include_earnings_transcripts"] is False
    assert captured["include_options"] is True


def test_cli_sec_filings_prints_json(monkeypatch):
    captured = {}

    monkeypatch.setattr(
        "cli.fetch_recent_filings",
        lambda *args, **kwargs: captured.update({"args": args, "kwargs": kwargs}) or {
            "ok": True,
            "ticker": args[0],
            "cik": "0000320193",
            "filings": [{"form": "8-K"}],
            "warnings": [],
            "errors": [],
        },
    )

    exit_code, output = _run_cli_and_capture(["sec-filings", "--ticker", "AAPL", "--limit", "3"])
    payload = json.loads(output)

    assert exit_code == 0
    assert payload["ticker"] == "AAPL"
    assert captured["kwargs"]["limit"] == 3
    assert captured["kwargs"]["config"]["SEC_RESEARCH_ENABLED"] == "true"


def test_cli_filing_sentiment_prints_json(monkeypatch):
    monkeypatch.setattr(
        "cli.fetch_recent_filings",
        lambda *args, **kwargs: {
            "ok": True,
            "ticker": args[0],
            "filings": [{"form": "8-K", "description": "Earnings release with raised guidance", "items": ["2.02"], "filing_url": None}],
            "warnings": [],
            "errors": [],
        },
    )

    exit_code, output = _run_cli_and_capture(["filing-sentiment", "--ticker", "AAPL", "--pretty"])
    payload = json.loads(output)

    assert exit_code == 0
    assert payload["filing_analysis"]["ok"] is True
    assert payload["filing_sentiment"]["ok"] is True


def test_cli_earnings_8k_prints_json(monkeypatch):
    monkeypatch.setattr(
        "cli.fetch_recent_filings",
        lambda *args, **kwargs: {
            "ok": True,
            "ticker": args[0],
            "filings": [
                {
                    "form": "8-K",
                    "filing_date": "2026-06-01",
                    "description": "Earnings release",
                    "items": ["2.02"],
                    "filing_url": "https://www.sec.gov/test.htm",
                }
            ],
            "warnings": [],
            "errors": [],
        },
    )
    monkeypatch.setattr(
        "cli.fetch_filing_text",
        lambda *args, **kwargs: {"ok": True, "text": "Record revenue and raised guidance.", "warnings": [], "errors": []},
    )

    exit_code, output = _run_cli_and_capture(["earnings-8k", "--ticker", "AAPL"])
    payload = json.loads(output)

    assert exit_code == 0
    assert payload["earnings_8k_analysis"]["sentiment_label"] == "positive"


def test_cli_short_interest_prints_json():
    exit_code, output = _run_cli_and_capture(
        [
            "short-interest",
            "--ticker",
            "AAPL",
            "--short-percent-float",
            "30",
            "--days-to-cover",
            "8",
            "--borrow-rate",
            "12",
        ]
    )
    payload = json.loads(output)

    assert exit_code == 0
    assert payload["ticker"] == "AAPL"
    assert payload["short_interest_level"] == "extreme"
    assert payload["squeeze_risk"] == "high"


def test_cli_news_sentiment_prints_json(monkeypatch):
    monkeypatch.setattr(
        "cli.fetch_recent_news",
        lambda *args, **kwargs: {
            "ok": True,
            "available": True,
            "articles": [{"headline": "AAPL analyst upgrade and buyback", "summary": ""}],
            "warnings": [],
            "errors": [],
        },
    )

    exit_code, output = _run_cli_and_capture(["news-sentiment", "--ticker", "AAPL"])
    payload = json.loads(output)

    assert exit_code == 0
    assert payload["news_sentiment"]["sentiment_label"] == "positive"


def test_cli_news_diagnostic_prints_json(monkeypatch):
    monkeypatch.setattr(
        "cli.diagnose_news_provider",
        lambda: {"ok": True, "provider": "ibkr_optional", "available": False, "warnings": ["disabled"], "errors": []},
    )

    exit_code, output = _run_cli_and_capture(["news-diagnostic", "--pretty"])
    payload = json.loads(output)

    assert exit_code == 0
    assert payload["provider"] == "ibkr_optional"


def test_cli_memory_search_prints_json_and_exits_zero(monkeypatch):
    captured = {}

    monkeypatch.setattr(
        "cli.search_trade_memory_tool",
        lambda **kwargs: captured.update(kwargs) or {
            "ok": True,
            "tool": "search_trade_memory_tool",
            "data": {"matches": []},
            "error": None,
        },
    )

    exit_code, output = _run_cli_and_capture(["memory-search", "--query", "AAPL breakout", "--top-k", "3"])
    payload = json.loads(output)

    assert exit_code == 0
    assert payload["tool"] == "search_trade_memory_tool"
    assert captured["query"] == "AAPL breakout"
    assert captured["top_k"] == 3
    assert "retrieval_quality" in payload


def test_cli_memory_search_accepts_ticker_and_setup(monkeypatch):
    captured = {}

    monkeypatch.setattr(
        "cli.search_trade_memory_tool",
        lambda **kwargs: captured.update(kwargs) or {
            "ok": True,
            "tool": "search_trade_memory_tool",
            "data": {"ok": True, "matches": []},
            "error": None,
        },
    )

    exit_code, output = _run_cli_and_capture(["memory-search", "--ticker", "AAPL", "--setup", "relative_strength"])
    payload = json.loads(output)

    assert exit_code == 0
    assert captured["query"] == "AAPL relative_strength"
    assert payload["retrieval_quality"]["quality_status"] == "fail"


def test_cli_memory_status_prints_json(monkeypatch, tmp_path):
    monkeypatch.setattr(
        "cli.check_runtime_readiness",
        lambda *args, **kwargs: {"ok": True, "categories": {"memory_ready": {"ok": True, "status": "ready_with_warnings"}}},
    )

    exit_code, output = _run_cli_and_capture(["memory-status", "--db-path", str(tmp_path / "memory.db"), "--pretty"])
    payload = json.loads(output)

    assert exit_code == 0
    assert payload["retrieval_quality_gate_available"] is True
    assert payload["annotation_store_available"] is True


def test_cli_annotate_trade_and_annotations_use_temp_db(tmp_path):
    db_path = str(tmp_path / "annotations.db")

    add_exit, add_output = _run_cli_and_capture(
        [
            "annotate-trade",
            "--ticker",
            "AAPL",
            "--setup",
            "relative_strength",
            "--rating",
            "-1",
            "--label",
            "bad setup",
            "--notes",
            "Failed because market regime was weak",
            "--db-path",
            db_path,
        ]
    )
    list_exit, list_output = _run_cli_and_capture(["annotations", "--ticker", "AAPL", "--db-path", db_path])

    assert add_exit == 0
    assert json.loads(add_output)["annotation"]["ticker"] == "AAPL"
    assert list_exit == 0
    payload = json.loads(list_output)
    assert payload["summary"]["negative_count"] == 1


def test_cli_memory_events_prints_json(tmp_path):
    from memory.annotation_store import record_memory_retrieval_event

    db_path = str(tmp_path / "events.db")
    record_memory_retrieval_event(
        db_path=db_path,
        run_id="run-1",
        ticker="AAPL",
        setup_type="relative_strength",
        query={"ticker": "AAPL"},
        retrieval_result={"ok": True, "matches": []},
        retrieval_quality={"quality_status": "fail"},
        used_for_decision=False,
        used_for_explanation=False,
    )

    exit_code, output = _run_cli_and_capture(["memory-events", "--db-path", db_path, "--pretty"])
    payload = json.loads(output)

    assert exit_code == 0
    assert payload["count"] == 1
    assert payload["events"][0]["ticker"] == "AAPL"


def test_cli_memory_store_note_prints_json_and_exits_zero(monkeypatch):
    captured = {}

    monkeypatch.setattr(
        "cli.store_trade_memory_tool",
        lambda **kwargs: captured.update(kwargs) or {
            "ok": True,
            "tool": "store_trade_memory_tool",
            "data": {"memory_id": "note-1"},
            "error": None,
        },
    )

    exit_code, output = _run_cli_and_capture(["memory-store-note", "--ticker", "AAPL", "--note", "Watch failed breakout retest."])
    payload = json.loads(output)

    assert exit_code == 0
    assert payload["tool"] == "store_trade_memory_tool"
    assert captured["item"]["ticker"] == "AAPL"
    assert captured["item"]["note"] == "Watch failed breakout retest."


def test_cli_review_closed_trades_prints_json_and_exits_zero(monkeypatch):
    captured = {}

    monkeypatch.setattr(
        "cli.review_closed_trades_tool",
        lambda **kwargs: captured.update(kwargs) or {
            "ok": True,
            "tool": "review_closed_trades_tool",
            "data": {"reviewed_count": 1, "errors": []},
            "error": None,
        },
    )

    exit_code, output = _run_cli_and_capture(["review-closed-trades", "--store-memory"])
    payload = json.loads(output)

    assert exit_code == 0
    assert payload["tool"] == "review_closed_trades_tool"
    assert captured["store_memory"] is True


def test_cli_trade_reviews_prints_json_and_exits_zero(monkeypatch):
    captured = {}

    monkeypatch.setattr(
        "cli.get_trade_reviews_tool",
        lambda **kwargs: captured.update(kwargs) or {
            "ok": True,
            "tool": "get_trade_reviews_tool",
            "data": {"count": 1, "reviews": [{"ticker": kwargs["ticker"]}]},
            "error": None,
        },
    )

    exit_code, output = _run_cli_and_capture(["trade-reviews", "--ticker", "AAPL", "--pretty"])
    payload = json.loads(output)

    assert exit_code == 0
    assert output.startswith("{\n  ")
    assert payload["tool"] == "get_trade_reviews_tool"
    assert captured["ticker"] == "AAPL"


def test_cli_report_prints_json_and_exits_zero(monkeypatch):
    captured = {}

    monkeypatch.setattr(
        "cli.generate_report_tool",
        lambda **kwargs: captured.update(kwargs) or {
            "ok": True,
            "tool": "generate_report_tool",
            "data": {
                "report_type": kwargs["report_type"],
                "format": kwargs["format"],
                "markdown": "# Report",
            },
            "error": None,
        },
    )

    exit_code, output = _run_cli_and_capture(["report", "--type", "performance", "--format", "dict"])
    payload = json.loads(output)

    assert exit_code == 0
    assert payload["tool"] == "generate_report_tool"
    assert captured["report_type"] == "performance"
    assert captured["format"] == "dict"


def test_cli_report_pretty_markdown_prints_markdown_only(monkeypatch):
    monkeypatch.setattr(
        "cli.generate_report_tool",
        lambda **kwargs: {
            "ok": True,
            "tool": "generate_report_tool",
            "data": {
                "report_type": kwargs["report_type"],
                "format": kwargs["format"],
                "markdown": "# Full Paper Trading Report\n\nSummary text.",
            },
            "error": None,
        },
    )

    exit_code, output = _run_cli_and_capture(["report", "--type", "full_paper_trading", "--format", "markdown", "--pretty"])

    assert exit_code == 0
    assert output.startswith("# Full Paper Trading Report")


def test_cli_env_check_prints_json(monkeypatch):
    monkeypatch.setattr(
        "cli.check_environment",
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

    exit_code, output = _run_cli_and_capture(["env-check", "--pretty"])
    payload = json.loads(output)

    assert exit_code == 0
    assert payload["ok"] is True
    assert payload["database"]["ok"] is True


def test_cli_live_dry_run_prints_json(monkeypatch):
    captured = {}

    monkeypatch.setattr(
        "cli.run_provider_dry_run",
        lambda **kwargs: captured.update(kwargs) or {
            "ok": True,
            "timestamp": "2026-06-08T00:00:00+00:00",
            "ticker": kwargs["ticker"],
            "checks": {},
            "warnings": ["dry run"],
            "errors": [],
        },
    )

    exit_code, output = _run_cli_and_capture(["live-dry-run", "--ticker", "AAPL", "--include-memory"])
    payload = json.loads(output)

    assert exit_code == 0
    assert payload["ticker"] == "AAPL"
    assert captured["include_memory"] is True


def test_cli_ibkr_options_diagnose_prints_json(monkeypatch):
    captured = {}

    monkeypatch.setattr(
        "cli.diagnose_ibkr_option_quotes",
        lambda **kwargs: captured.update(kwargs) or {
            "ok": True,
            "ticker": kwargs["ticker"],
            "permissions_summary": {"option_quotes_available": True},
            "warnings": [],
            "errors": [],
        },
    )

    exit_code, output = _run_cli_and_capture(["ibkr-options-diagnose", "--ticker", "SPY", "--max-contracts", "3"])
    payload = json.loads(output)

    assert exit_code == 0
    assert payload["ticker"] == "SPY"
    assert captured["ticker"] == "SPY"
    assert captured["max_contracts"] == 3


def test_cli_risk_diagnostics_prints_json_and_exits_zero(monkeypatch):
    monkeypatch.setattr(
        "cli.get_paper_risk_diagnostics",
        lambda **kwargs: {
            "ok": True,
            "mode": "paper_trading",
            "circuit_breaker": {"circuit_status": "normal"},
            "setup_decay": {"setups": {}},
            "warnings": [],
            "errors": [],
        },
    )

    exit_code, output = _run_cli_and_capture(["risk-diagnostics", "--pretty"])
    payload = json.loads(output)

    assert exit_code == 0
    assert output.startswith("{\n  ")
    assert payload["ok"] is True
    assert payload["circuit_breaker"]["circuit_status"] == "normal"


def test_cli_macro_calendar_prints_json(monkeypatch):
    captured = {}

    monkeypatch.setattr(
        "cli.get_macro_calendar",
        lambda **kwargs: captured.update(kwargs) or {
            "ok": True,
            "source": "static",
            "events": [{"event_type": "CPI"}],
            "count": 1,
            "error": None,
        },
    )

    exit_code, output = _run_cli_and_capture(["macro-calendar", "--days", "7", "--pretty"])
    payload = json.loads(output)

    assert exit_code == 0
    assert payload["ok"] is True
    assert payload["events"][0]["event_type"] == "CPI"
    assert captured["start_date"] <= captured["end_date"]


def test_cli_macro_risk_prints_json(monkeypatch):
    monkeypatch.setattr(
        "cli.evaluate_macro_risk",
        lambda: {
            "ok": True,
            "macro_risk_level": "medium",
            "risk_multiplier": 0.75,
            "new_trades_allowed": True,
            "warnings": [],
            "reasons": [],
        },
    )

    exit_code, output = _run_cli_and_capture(["macro-risk", "--pretty"])
    payload = json.loads(output)

    assert exit_code == 0
    assert payload["macro_risk_level"] == "medium"
    assert payload["risk_multiplier"] == 0.75


def test_cli_correlation_refresh_prints_json(monkeypatch):
    captured = {}

    monkeypatch.setattr(
        "cli.refresh_correlation_snapshot",
        lambda **kwargs: captured.update(kwargs) or {
            "ok": True,
            "matrix": {"tickers": kwargs["tickers"]},
            "save_result": {"ok": True, "snapshot_id": "snap-1"},
            "warnings": [],
            "errors": [],
        },
    )

    exit_code, output = _run_cli_and_capture(["correlation-refresh", "--tickers", "AAPL", "MSFT", "SPY", "--pretty"])
    payload = json.loads(output)

    assert exit_code == 0
    assert payload["ok"] is True
    assert captured["tickers"] == ["AAPL", "MSFT", "SPY"]
    assert captured["lookback_days"] == 60


def test_cli_correlation_status_prints_json(monkeypatch):
    monkeypatch.setattr(
        "cli.get_latest_correlation_snapshot",
        lambda **kwargs: {
            "ok": True,
            "snapshot": {"snapshot_id": "snap-1", "age_hours": 1.2},
            "is_stale": False,
            "error": None,
        },
    )

    exit_code, output = _run_cli_and_capture(["correlation-status", "--pretty"])
    payload = json.loads(output)

    assert exit_code == 0
    assert payload["snapshot"]["snapshot_id"] == "snap-1"


def test_cli_concentration_check_prints_json(monkeypatch):
    monkeypatch.setattr(
        "cli.get_latest_correlation_snapshot",
        lambda **kwargs: {
            "ok": True,
            "snapshot": {"matrix_json": {"AAPL": {"MSFT": 0.9}}, "tickers_json": ["AAPL", "MSFT"]},
            "is_stale": False,
        },
    )
    monkeypatch.setattr(
        "cli.get_open_recommendations",
        lambda **kwargs: [{"ticker": "MSFT", "sector": "tech", "entry_price": 100.0, "stop_loss": 95.0, "quantity": 20}],
    )
    monkeypatch.setattr(
        "cli.evaluate_concentration_risk",
        lambda candidate, open_trades, correlation_matrix=None, config=None: {
            "ok": True,
            "approved": True,
            "risk_level": "high",
            "risk_multiplier": 0.5,
            "warnings": [],
            "reasons": ["mocked"],
        },
    )

    exit_code, output = _run_cli_and_capture(["concentration-check", "--ticker", "AAPL", "--pretty"])
    payload = json.loads(output)

    assert exit_code == 0
    assert payload["ticker"] == "AAPL"
    assert payload["concentration_risk"]["risk_multiplier"] == 0.5


def test_cli_volume_profile_prints_json(monkeypatch):
    bars = [
        {"timestamp": f"2026-01-{(index % 28) + 1:02d}", "close": 100 + index * 0.1, "volume": 1_000_000}
        for index in range(80)
    ]
    monkeypatch.setattr(
        "cli.get_historical_bars",
        lambda ticker, lookback_days=90: {"ok": True, "ticker": ticker, "data": {"bars": bars}, "error": None},
    )

    exit_code, output = _run_cli_and_capture(["volume-profile", "--ticker", "AAPL", "--pretty"])
    payload = json.loads(output)

    assert exit_code == 0
    assert payload["ticker"] == "AAPL"
    assert payload["volume_profile"]["point_of_control"] is not None


def test_cli_timeframe_check_prints_json(monkeypatch):
    bars = [
        {"timestamp": f"2026-01-{(index % 28) + 1:02d}", "high": 100 + index + 1, "low": 100 + index - 1, "close": 100 + index, "volume": 1_000_000}
        for index in range(220)
    ]
    monkeypatch.setattr(
        "cli.get_historical_bars",
        lambda ticker, lookback_days=180: {"ok": True, "ticker": ticker, "data": {"bars": bars}, "error": None},
    )

    exit_code, output = _run_cli_and_capture(["timeframe-check", "--ticker", "AAPL", "--pretty"])
    payload = json.loads(output)

    assert exit_code == 0
    assert payload["ticker"] == "AAPL"
    assert payload["timeframe_confirmation"]["daily_trend"] == "uptrend"


def _mock_options_chain(ticker: str) -> dict:
    return {
        "ok": True,
        "ticker": ticker,
        "data": {
            "contracts": [
                {
                    "option_contract": f"{ticker}260717C00125000",
                    "underlying_ticker": ticker,
                    "option_type": "call",
                    "strike": 125.0,
                    "expiration": "2026-07-17",
                    "days_to_expiration": 32,
                    "bid": 3.9,
                    "ask": 4.1,
                    "mid": 4.0,
                    "implied_volatility": 0.28,
                    "iv_rank": 18,
                    "iv_percentile": 22,
                    "delta": 0.52,
                    "gamma": 0.04,
                    "theta": -0.04,
                    "vega": 0.12,
                    "underlying_price": 120.0,
                },
                {
                    "option_contract": f"{ticker}260717P00115000",
                    "underlying_ticker": ticker,
                    "option_type": "put",
                    "strike": 115.0,
                    "expiration": "2026-07-17",
                    "days_to_expiration": 32,
                    "bid": 2.8,
                    "ask": 3.0,
                    "mid": 2.9,
                    "implied_volatility": 0.3,
                    "iv_rank": 35,
                    "iv_percentile": 45,
                    "delta": -0.42,
                    "gamma": 0.04,
                    "theta": -0.04,
                    "vega": 0.12,
                    "underlying_price": 120.0,
                }
            ]
        },
        "error": None,
    }


def test_cli_iv_rank_prints_json(monkeypatch):
    monkeypatch.setattr("cli.get_options_chain", _mock_options_chain)

    exit_code, output = _run_cli_and_capture(["iv-rank", "--ticker", "AAPL", "--pretty"])
    payload = json.loads(output)

    assert exit_code == 0
    assert payload["ticker"] == "AAPL"
    assert payload["iv_context"]["iv_rank"] == 18


def test_cli_greeks_check_prints_json(monkeypatch):
    monkeypatch.setattr("cli.get_options_chain", _mock_options_chain)

    exit_code, output = _run_cli_and_capture(["greeks-check", "--ticker", "AAPL", "--pretty"])
    payload = json.loads(output)

    assert exit_code == 0
    assert payload["greeks_monitoring"]["greeks_quality"] in {"good", "usable"}


def test_cli_option_risk_check_prints_json(monkeypatch):
    monkeypatch.setattr("cli.get_options_chain", _mock_options_chain)

    exit_code, output = _run_cli_and_capture(["option-risk-check", "--ticker", "AAPL", "--pretty"])
    payload = json.loads(output)

    assert exit_code == 0
    assert payload["option_trade_risk"]["approved"] is True


def test_cli_option_strategies_prints_json(monkeypatch):
    monkeypatch.setattr("cli.get_options_chain", _mock_options_chain)

    exit_code, output = _run_cli_and_capture(["option-strategies", "--ticker", "AAPL", "--pretty"])
    payload = json.loads(output)

    assert exit_code == 0
    assert payload["strategy_result"]["summary"]["strategy_count"] >= 1


def test_cli_option_strategy_check_prints_json(monkeypatch):
    monkeypatch.setattr("cli.get_options_chain", _mock_options_chain)

    exit_code, output = _run_cli_and_capture(["option-strategy-check", "--ticker", "AAPL", "--strategy", "long_call", "--pretty"])
    payload = json.loads(output)

    assert exit_code == 0
    assert payload["requested_strategy"] == "long_call"
    assert payload["strategy"]["strategy_type"] == "long_call"


def test_cli_db_migrate_prints_json_and_exits_zero(monkeypatch):
    monkeypatch.setattr(
        "cli.apply_pending_migrations",
        lambda **kwargs: {
            "ok": True,
            "db_path": kwargs["db_path"],
            "applied": [],
            "skipped": [],
            "failed": [],
            "migration_count": 5,
        },
    )

    exit_code, output = _run_cli_and_capture(["db-migrate", "--db-path", "test.db", "--pretty"])
    payload = json.loads(output)

    assert exit_code == 0
    assert payload["ok"] is True
    assert payload["db_path"] == "test.db"


def test_cli_performance_attribution_prints_json(monkeypatch):
    monkeypatch.setattr("cli.get_trade_history", lambda **kwargs: [{"ticker": "AAPL", "outcome": "win", "risk_reward": 2.0}])

    exit_code, output = _run_cli_and_capture(["performance-attribution", "--pretty"])
    payload = json.loads(output)

    assert exit_code == 0
    assert payload["ok"] is True
    assert payload["closed_trade_count"] == 1


def test_cli_setup_diagnostics_prints_json(monkeypatch):
    monkeypatch.setattr("cli.get_trade_history", lambda **kwargs: [{"ticker": "AAPL", "setup_type": "breakout", "outcome": "win", "risk_reward": 2.0}])

    exit_code, output = _run_cli_and_capture(["setup-diagnostics", "--pretty"])
    payload = json.loads(output)

    assert exit_code == 0
    assert payload["ok"] is True
    assert payload["setups"][0]["setup_type"] == "breakout"


def test_cli_filter_attribution_prints_json(monkeypatch):
    monkeypatch.setattr("cli.get_candidate_decision_history", lambda **kwargs: [{"ticker": "AAPL", "passed_constraints": False, "rejection_reason": "data_quality stale"}])
    monkeypatch.setattr("cli.get_trade_history", lambda **kwargs: [])

    exit_code, output = _run_cli_and_capture(["filter-attribution", "--pretty"])
    payload = json.loads(output)

    assert exit_code == 0
    assert payload["ok"] is True
    assert any(item["filter_name"] == "data_quality" for item in payload["filters"])


def test_cli_trade_errors_prints_json(monkeypatch):
    monkeypatch.setattr("cli.get_trade_history", lambda **kwargs: [{"ticker": "AAPL", "outcome": "loss", "entry_price": 100, "stop_loss": 95, "exit_price": 95, "max_drawdown": -1.2, "max_gain": 0.1}])

    exit_code, output = _run_cli_and_capture(["trade-errors", "--pretty"])
    payload = json.loads(output)

    assert exit_code == 0
    assert payload["ok"] is True
    assert payload["top_failure_modes"][0]["category"] == "stop_too_tight"


def test_cli_performance_report_prints_markdown(monkeypatch):
    monkeypatch.setattr(
        "cli.generate_performance_diagnostics_report",
        lambda **kwargs: {"ok": True, "report_type": "performance_diagnostics", "markdown": "# Paper Performance Diagnostics\n\nBody", "errors": []},
    )

    exit_code, output = _run_cli_and_capture(["performance-report", "--pretty"])

    assert exit_code == 0
    assert output.startswith("# Paper Performance Diagnostics")


def test_cli_db_status_prints_json_and_exits_zero(monkeypatch):
    monkeypatch.setattr("cli.get_schema_version", lambda **kwargs: {"ok": True, "current_version": "005_trade_tracking_tables", "migration_count": 5})
    monkeypatch.setattr("cli.validate_schema", lambda **kwargs: {"ok": True, "tables": {"audit_events": True}, "errors": []})
    monkeypatch.setattr("cli.verify_audit_chain", lambda **kwargs: {"ok": True, "event_count": 0, "errors": []})
    monkeypatch.setattr("cli.list_recent_pipeline_runs", lambda **kwargs: {"ok": True, "count": 2, "pipeline_runs": []})

    exit_code, output = _run_cli_and_capture(["db-status", "--pretty"])
    payload = json.loads(output)

    assert exit_code == 0
    assert payload["ok"] is True
    assert payload["schema_version"]["current_version"] == "005_trade_tracking_tables"
    assert payload["recent_pipeline_runs_count"] == 2


def test_cli_pipeline_runs_prints_json_and_exits_zero(monkeypatch):
    monkeypatch.setattr(
        "cli.list_recent_pipeline_runs",
        lambda **kwargs: {"ok": True, "count": 1, "pipeline_runs": [{"run_id": "run-1"}]},
    )

    exit_code, output = _run_cli_and_capture(["pipeline-runs", "--limit", "10"])
    payload = json.loads(output)

    assert exit_code == 0
    assert payload["pipeline_runs"][0]["run_id"] == "run-1"


def test_cli_audit_log_prints_json_and_exits_zero(monkeypatch):
    monkeypatch.setattr(
        "cli.list_audit_events",
        lambda **kwargs: {"ok": True, "count": 1, "events": [{"event_type": "paper_cycle_started"}]},
    )

    exit_code, output = _run_cli_and_capture(["audit-log", "--limit", "20"])
    payload = json.loads(output)

    assert exit_code == 0
    assert payload["events"][0]["event_type"] == "paper_cycle_started"


def test_cli_config_check_prints_json_and_exits_zero(monkeypatch):
    monkeypatch.setattr(
        "cli.validate_startup_config",
        lambda config=None: {"ok": True, "readiness": "ready_with_warnings", "errors": []},
    )

    exit_code, output = _run_cli_and_capture(["config-check", "--pretty"])
    payload = json.loads(output)

    assert exit_code == 0
    assert payload["readiness"] == "ready_with_warnings"


def test_cli_readiness_check_prints_json_and_exits_zero(monkeypatch):
    captured = {}

    monkeypatch.setattr(
        "cli.check_runtime_readiness",
        lambda config=None, include_live_checks=False: captured.update({"include_live_checks": include_live_checks}) or {"ok": True, "readiness": "ready", "errors": []},
    )

    exit_code, output = _run_cli_and_capture(["readiness-check", "--include-live-checks", "--pretty"])
    payload = json.loads(output)

    assert exit_code == 0
    assert payload["readiness"] == "ready"
    assert captured["include_live_checks"] is True


def test_cli_jobs_prints_registered_jobs(monkeypatch):
    monkeypatch.setattr(
        "cli.list_registered_jobs",
        lambda: {"ok": True, "jobs": [{"job_name": "weekly_paper_cycle"}], "errors": []},
    )

    exit_code, output = _run_cli_and_capture(["jobs"])
    payload = json.loads(output)

    assert exit_code == 0
    assert payload["jobs"][0]["job_name"] == "weekly_paper_cycle"


def test_cli_job_run_prints_result_and_preserves_dry_run_default(monkeypatch):
    captured = {}

    monkeypatch.setattr(
        "cli.run_registered_job",
        lambda job_name, db_path=None, dry_run=True: captured.update({"job_name": job_name, "dry_run": dry_run}) or {
            "ok": True,
            "job_name": job_name,
            "status": "success",
            "dry_run": dry_run,
            "errors": [],
        },
    )

    exit_code, output = _run_cli_and_capture(["job-run", "--job", "weekly_paper_cycle"])
    payload = json.loads(output)

    assert exit_code == 0
    assert payload["status"] == "success"
    assert captured == {"job_name": "weekly_paper_cycle", "dry_run": True}


def test_cli_jobs_due_prints_result(monkeypatch):
    captured = {}

    monkeypatch.setattr(
        "cli.run_due_jobs",
        lambda db_path=None, now=None, dry_run=True: captured.update({"now": now, "dry_run": dry_run}) or {
            "ok": True,
            "ran_count": 0,
            "results": [],
            "errors": [],
        },
    )

    exit_code, output = _run_cli_and_capture(["jobs-due", "--now", "2026-06-15T09:00:00-04:00"])
    payload = json.loads(output)

    assert exit_code == 0
    assert payload["ran_count"] == 0
    assert captured["dry_run"] is True


def test_cli_job_history_prints_result(monkeypatch):
    monkeypatch.setattr(
        "cli.list_job_runs",
        lambda **kwargs: {"ok": True, "count": 1, "job_runs": [{"job_name": "healthcheck"}], "error": None},
    )

    exit_code, output = _run_cli_and_capture(["job-history", "--limit", "5"])
    payload = json.loads(output)

    assert exit_code == 0
    assert payload["job_runs"][0]["job_name"] == "healthcheck"


def test_cli_alerts_prints_result(monkeypatch):
    monkeypatch.setattr(
        "cli.list_alerts",
        lambda **kwargs: {"ok": True, "count": 1, "alerts": [{"severity": "warning"}], "severity_counts": {"warning": 1}},
    )

    exit_code, output = _run_cli_and_capture(["alerts", "--severity", "warning"])
    payload = json.loads(output)

    assert exit_code == 0
    assert payload["severity_counts"]["warning"] == 1


def test_cli_alert_test_creates_local_alert(monkeypatch):
    monkeypatch.setattr(
        "cli.create_alert",
        lambda **kwargs: {"ok": True, "alert": {"severity": kwargs["severity"], "alert_type": kwargs["alert_type"]}, "error": None},
    )

    exit_code, output = _run_cli_and_capture(["alert-test", "--severity", "critical"])
    payload = json.loads(output)

    assert exit_code == 0
    assert payload["alert"]["severity"] == "critical"
    assert payload["alert"]["alert_type"] == "test_alert"


def test_cli_gemini_prompt_preview_prints_structured_prompt():
    exit_code, output = _run_cli_and_capture(["gemini-prompt-preview", "--pretty"])
    payload = json.loads(output)

    assert exit_code == 0
    assert payload["ok"] is True
    assert payload["mode"] == "weekly-trade-hunt"
    assert "Do not invent tickers" in payload["system_prompt"]
    assert "Deterministic trading-brain result" in payload["prompt"]
    assert "AAPL" in payload["prompt"]


def test_cli_validate_gemini_output_prints_validation_result():
    exit_code, output = _run_cli_and_capture(["validate-gemini-output", "--pretty"])
    payload = json.loads(output)

    assert exit_code == 0
    assert payload["ok"] is True
    assert payload["validation"]["validation_status"] == "pass"
    assert payload["validation"]["safe_to_show_user"] is True


def test_cli_format_trade_response_prints_validated_and_fallback_text():
    exit_code, output = _run_cli_and_capture(["format-trade-response", "--pretty"])
    payload = json.loads(output)

    assert exit_code == 0
    assert payload["ok"] is True
    assert "Paper trading only" in payload["validated_response"]
    assert "Paper trading only" in payload["fallback_response"]
    assert payload["validation"]["validation_status"] == "pass"


def test_cli_exits_one_when_job_fails(monkeypatch):
    monkeypatch.setattr(
        "cli.run_paper_summary_job",
        lambda **kwargs: {
            "ok": False,
            "job": "paper_summary",
            "mode": "paper_trading",
            "errors": ["boom"],
        },
    )

    exit_code, output = _run_cli_and_capture(["paper-summary"])
    output = output.strip()
    payload = json.loads(output)

    assert exit_code == 1
    assert payload["ok"] is False
    assert payload["errors"] == ["boom"]


def test_cli_pretty_output_is_valid_indented_json(monkeypatch):
    monkeypatch.setattr(
        "cli.run_paper_summary_job",
        lambda **kwargs: {
            "ok": True,
            "job": "paper_summary",
            "mode": "paper_trading",
            "warning": "simulated only",
            "errors": [],
        },
    )

    exit_code, output = _run_cli_and_capture(["paper-summary", "--pretty"])
    payload = json.loads(output)

    assert exit_code == 0
    assert output.startswith("{\n  ")
    assert payload["job"] == "paper_summary"


def test_cli_does_not_expose_buy_sell_or_order_commands():
    parser = cli.build_parser()
    subparsers_action = next(action for action in parser._actions if getattr(action, "choices", None))
    command_names = set(subparsers_action.choices.keys())

    assert "paper-cycle" in command_names
    assert "paper-review" in command_names
    assert "paper-summary" in command_names
    assert "research-brief" in command_names
    assert "memory-search" in command_names
    assert "memory-status" in command_names
    assert "annotate-trade" in command_names
    assert "annotations" in command_names
    assert "memory-events" in command_names
    assert "memory-store-note" in command_names
    assert "review-closed-trades" in command_names
    assert "trade-reviews" in command_names
    assert "report" in command_names
    assert "performance-attribution" in command_names
    assert "setup-diagnostics" in command_names
    assert "filter-attribution" in command_names
    assert "trade-errors" in command_names
    assert "performance-report" in command_names
    assert "env-check" in command_names
    assert "live-dry-run" in command_names
    assert "ibkr-diagnose" in command_names
    assert "ibkr-options-diagnose" in command_names
    assert "risk-diagnostics" in command_names
    assert "macro-calendar" in command_names
    assert "macro-risk" in command_names
    assert "correlation-refresh" in command_names
    assert "correlation-status" in command_names
    assert "concentration-check" in command_names
    assert "volume-profile" in command_names
    assert "timeframe-check" in command_names
    assert "iv-rank" in command_names
    assert "greeks-check" in command_names
    assert "option-risk-check" in command_names
    assert "option-strategies" in command_names
    assert "option-strategy-check" in command_names
    assert "db-status" in command_names
    assert "db-migrate" in command_names
    assert "pipeline-runs" in command_names
    assert "audit-log" in command_names
    assert "config-check" in command_names
    assert "readiness-check" in command_names
    assert "jobs" in command_names
    assert "job-run" in command_names
    assert "jobs-due" in command_names
    assert "job-history" in command_names
    assert "alerts" in command_names
    assert "alert-test" in command_names
    assert "gemini-prompt-preview" in command_names
    assert "validate-gemini-output" in command_names
    assert "format-trade-response" in command_names
    assert "buy" not in command_names
    assert "sell" not in command_names
    assert "order" not in command_names
    assert "orders" not in command_names
    assert "execute" not in command_names
    assert "brokerage" not in command_names
