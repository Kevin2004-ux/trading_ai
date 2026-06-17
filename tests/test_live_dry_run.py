from diagnostics import live_dry_run
from diagnostics.live_dry_run import run_provider_dry_run


def test_provider_dry_run_returns_unavailable_cleanly_when_api_keys_missing(monkeypatch):
    monkeypatch.setattr(live_dry_run, "_env_or_config", lambda name: None)
    monkeypatch.setattr(live_dry_run, "get_selected_market_data_provider", lambda: "polygon")
    monkeypatch.setattr(live_dry_run, "get_selected_options_data_provider", lambda: "polygon")
    monkeypatch.setattr(
        live_dry_run,
        "evaluate_macro_risk",
        lambda: {"ok": True, "macro_risk_level": "low", "risk_multiplier": 1.0, "new_trades_allowed": True, "warnings": [], "reasons": []},
    )

    result = run_provider_dry_run(ticker="AAPL", include_memory=True)

    assert result["ok"] is True
    assert result["ticker"] == "AAPL"
    assert result["checks"]["market_data"]["status"] == "unavailable"
    assert result["checks"]["news"]["status"] == "unavailable"
    assert result["checks"]["options"]["status"] == "unavailable"
    assert result["checks"]["option_risk"]["status"] == "unavailable"
    assert "unavailable" in result["checks"]["option_risk"]["error"].lower()
    assert "startup_readiness" in result
    assert result["macro_risk"]["macro_risk_level"] == "low"
    assert "database_readiness" in result
    assert "provider_config_readiness" in result
    assert "options_blocked_status" in result
    assert "short_interest_research" in result["checks"]
    assert "news_research" in result["checks"]
    assert "gemini_validation" in result["checks"]
    assert result["checks"]["gemini_validation"]["usable"] is True
    assert result["checks"]["gemini_validation"]["data"]["data"]["gemini_called"] is False
    assert result["checks"]["gemini_validation"]["data"]["data"]["structured_output_validation_available"] is True
    assert "memory_readiness" in result["checks"]
    assert result["checks"]["memory_readiness"]["usable"] is True
    assert result["checks"]["memory_readiness"]["data"]["data"]["retrieval_quality_gate_available"] is True
    assert result["checks"]["memory_readiness"]["data"]["data"]["annotation_store_available"] is True
    assert "scheduler_alerts" in result["checks"]
    assert result["checks"]["scheduler_alerts"]["usable"] is True
    assert result["checks"]["scheduler_alerts"]["data"]["data"]["registered_jobs_count"] >= 1
    assert "performance_analytics" in result["checks"]
    assert result["checks"]["performance_analytics"]["usable"] is True
    assert result["checks"]["performance_analytics"]["data"]["data"]["performance_analytics_available"] is True
    assert result["checks"]["performance_analytics"]["data"]["data"]["setup_diagnostics_available"] is True
    assert "stress_testing" in result["checks"]
    assert result["checks"]["stress_testing"]["usable"] is True
    assert result["checks"]["stress_testing"]["data"]["data"]["default_scenario_count"] >= 18
    assert result["errors"] == []


def test_provider_dry_run_handles_mocked_successful_market_data(monkeypatch):
    monkeypatch.setattr(
        live_dry_run,
        "_env_or_config",
        lambda name: "configured" if name == "POLYGON_API_KEY" else None,
    )
    monkeypatch.setattr(live_dry_run, "get_selected_market_data_provider", lambda: "polygon")
    monkeypatch.setattr(live_dry_run, "get_selected_options_data_provider", lambda: "polygon")
    monkeypatch.setattr(
        live_dry_run,
        "get_market_snapshot",
        lambda ticker: {
            "ok": True,
            "ticker": ticker,
            "source": "polygon",
            "data": {"row_count": 180},
            "error": None,
        },
    )

    result = run_provider_dry_run(
        ticker="MSFT",
        include_market_data=True,
        include_news=False,
        include_sec_filings=False,
        include_earnings_transcripts=False,
        include_options=False,
    )

    assert result["ok"] is True
    assert result["checks"]["market_data"]["usable"] is True
    assert result["checks"]["market_data"]["data"]["ticker"] == "MSFT"


def test_provider_dry_run_reports_technical_confirmation_when_bars_available(monkeypatch):
    bars = [
        {"timestamp": f"2026-01-{(index % 28) + 1:02d}", "high": 100 + index + 1, "low": 100 + index - 1, "close": 100 + index, "volume": 1_000_000}
        for index in range(220)
    ]
    monkeypatch.setattr(
        live_dry_run,
        "_env_or_config",
        lambda name: "configured" if name == "POLYGON_API_KEY" else None,
    )
    monkeypatch.setattr(live_dry_run, "get_selected_market_data_provider", lambda: "polygon")
    monkeypatch.setattr(live_dry_run, "get_selected_options_data_provider", lambda: "polygon")
    monkeypatch.setattr(
        live_dry_run,
        "get_market_snapshot",
        lambda ticker: {
            "ok": True,
            "ticker": ticker,
            "source": "polygon",
            "data": {
                "bars": bars,
                "technical_snapshot": {"current_price": bars[-1]["close"]},
                "data_quality": {"quality_label": "fresh", "warnings": []},
            },
            "error": None,
        },
    )

    result = run_provider_dry_run(
        ticker="AAPL",
        include_market_data=True,
        include_news=False,
        include_sec_filings=False,
        include_earnings_transcripts=False,
        include_options=False,
    )

    assert result["ok"] is True
    assert result["checks"]["technical_confirmation"]["usable"] is True
    assert "timeframe_confirmation" in result["checks"]["technical_confirmation"]["data"]["data"]


def test_provider_dry_run_reports_sec_user_agent_missing(monkeypatch):
    def fake_env(name):
        if name in {"SEC_RESEARCH_ENABLED", "ENABLE_SEC_RESEARCH"}:
            return "true"
        if name == "POLYGON_API_KEY":
            return "configured"
        return None

    monkeypatch.setattr(live_dry_run, "_env_or_config", fake_env)
    monkeypatch.setattr(live_dry_run, "get_selected_market_data_provider", lambda: "polygon")
    monkeypatch.setattr(live_dry_run, "get_selected_options_data_provider", lambda: "polygon")

    result = run_provider_dry_run(
        ticker="AAPL",
        include_market_data=False,
        include_news=False,
        include_sec_filings=True,
        include_earnings_transcripts=False,
        include_options=False,
    )

    assert result["ok"] is True
    assert result["checks"]["sec_filings"]["provider"] == "sec_edgar"
    assert result["checks"]["sec_filings"]["status"] == "unavailable"
    assert "SEC_USER_AGENT" in result["checks"]["sec_filings"]["error"]


def test_provider_dry_run_reports_sec_filing_sentiment(monkeypatch):
    def fake_env(name):
        if name == "SEC_RESEARCH_ENABLED":
            return "true"
        if name in {"SEC_USER_AGENT", "POLYGON_API_KEY"}:
            return "configured"
        return None

    monkeypatch.setattr(live_dry_run, "_env_or_config", fake_env)
    monkeypatch.setattr(live_dry_run, "get_selected_market_data_provider", lambda: "polygon")
    monkeypatch.setattr(live_dry_run, "get_selected_options_data_provider", lambda: "polygon")
    monkeypatch.setattr(
        live_dry_run,
        "fetch_recent_filings",
        lambda *args, **kwargs: {
            "ok": True,
            "filings": [
                {
                    "form": "8-K",
                    "filing_date": "2026-06-01",
                    "description": "Earnings release with raised guidance",
                    "items": ["2.02"],
                    "filing_url": None,
                }
            ],
            "warnings": [],
            "errors": [],
        },
    )

    result = run_provider_dry_run(
        ticker="AAPL",
        include_market_data=False,
        include_news=False,
        include_sec_filings=True,
        include_earnings_transcripts=False,
        include_options=False,
    )

    assert result["ok"] is True
    assert result["checks"]["sec_filings"]["usable"] is True
    data = result["checks"]["sec_filings"]["data"]["data"]
    assert data["filings_loaded"] == 1
    assert data["filing_sentiment_evaluated"] is True


def test_provider_dry_run_reports_news_research_sentiment(monkeypatch):
    def fake_env(name):
        if name == "NEWS_RESEARCH_ENABLED":
            return "true"
        if name == "POLYGON_API_KEY":
            return "configured"
        return None

    monkeypatch.setattr(live_dry_run, "_env_or_config", fake_env)
    monkeypatch.setattr(live_dry_run, "get_selected_market_data_provider", lambda: "polygon")
    monkeypatch.setattr(live_dry_run, "get_selected_options_data_provider", lambda: "polygon")
    monkeypatch.setattr(
        live_dry_run,
        "fetch_recent_news",
        lambda *args, **kwargs: {
            "ok": True,
            "available": True,
            "articles": [{"headline": "AAPL faces investigation and lawsuit", "summary": ""}],
            "warnings": [],
            "errors": [],
        },
    )
    monkeypatch.setattr(live_dry_run, "diagnose_news_provider", lambda config=None: {"ok": True, "provider": "mock", "available": True, "warnings": [], "errors": []})

    result = run_provider_dry_run(
        ticker="AAPL",
        include_market_data=False,
        include_news=False,
        include_sec_filings=False,
        include_earnings_transcripts=False,
        include_options=False,
    )

    assert result["checks"]["news_research"]["data"]["data"]["headline_risk_status"] == "high"
    assert result["checks"]["news_research"]["data"]["data"]["research_risk_blocks_or_reduces"] is True


def test_provider_dry_run_reports_option_risk_when_option_quotes_available(monkeypatch):
    monkeypatch.setattr(
        live_dry_run,
        "_env_or_config",
        lambda name: "configured" if name == "POLYGON_API_KEY" else None,
    )
    monkeypatch.setattr(live_dry_run, "get_selected_market_data_provider", lambda: "polygon")
    monkeypatch.setattr(live_dry_run, "get_selected_options_data_provider", lambda: "polygon")
    monkeypatch.setattr(
        live_dry_run,
        "get_options_chain",
        lambda ticker: {
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
                        "delta": 0.52,
                        "gamma": 0.04,
                        "theta": -0.04,
                        "vega": 0.12,
                        "underlying_price": 120.0,
                    }
                ]
            },
            "error": None,
        },
    )

    result = run_provider_dry_run(
        ticker="AAPL",
        include_market_data=False,
        include_news=False,
        include_sec_filings=False,
        include_earnings_transcripts=False,
        include_options=True,
    )

    assert result["ok"] is True
    assert result["checks"]["option_risk"]["usable"] is True
    data = result["checks"]["option_risk"]["data"]["data"]
    assert data["iv_available"] is True
    assert data["greeks_available"] is True
    assert data["option_trade_risk"]["approved"] is True
    assert result["checks"]["option_strategy_engine"]["usable"] is True
    strategy_data = result["checks"]["option_strategy_engine"]["data"]["data"]["strategy_result"]
    assert strategy_data["summary"]["strategy_count"] >= 1


def test_provider_dry_run_handles_mocked_provider_failure(monkeypatch):
    monkeypatch.setattr(
        live_dry_run,
        "_env_or_config",
        lambda name: "configured" if name == "POLYGON_API_KEY" else None,
    )
    monkeypatch.setattr(live_dry_run, "get_selected_market_data_provider", lambda: "polygon")
    monkeypatch.setattr(live_dry_run, "get_selected_options_data_provider", lambda: "polygon")

    def fail_market_snapshot(ticker):
        raise RuntimeError("provider boom")

    monkeypatch.setattr(live_dry_run, "get_market_snapshot", fail_market_snapshot)

    result = run_provider_dry_run(
        ticker="AAPL",
        include_market_data=True,
        include_news=False,
        include_sec_filings=False,
        include_earnings_transcripts=False,
        include_options=False,
    )

    assert result["ok"] is False
    assert result["checks"]["market_data"]["status"] == "failed"
    assert any("provider boom" in error for error in result["errors"])


def test_provider_dry_run_reports_ibkr_provider_status(monkeypatch):
    monkeypatch.setattr(live_dry_run, "get_selected_market_data_provider", lambda: "ibkr")
    monkeypatch.setattr(live_dry_run, "get_selected_options_data_provider", lambda: "ibkr")
    monkeypatch.setattr(
        "providers.ibkr_provider.check_ibkr_connection",
        lambda: {
            "ok": True,
            "source": "ibkr",
            "connected": True,
            "use_delayed_data": True,
            "error": None,
        },
    )
    monkeypatch.setattr(
        live_dry_run,
        "get_market_snapshot",
        lambda ticker: {
            "ok": True,
            "ticker": ticker,
            "source": "ibkr",
            "data": {
                "row_count": 180,
                "use_delayed_data": True,
                "quote_fallback_used": True,
                "data_quality_warnings": ["IBKR quote unavailable; using latest historical close."],
            },
            "error": None,
        },
    )
    monkeypatch.setattr(
        "providers.ibkr_provider.diagnose_ibkr_option_quotes",
        lambda ticker, max_contracts=5: {
            "ok": True,
            "ticker": ticker,
            "underlying_quote": {"ok": True, "last_price": 101.0},
            "metadata": {"ok": True, "matching_expirations": ["2026-07-17"], "strike_count": 2},
            "contracts_tested": [{"option_contract": "AAPL20260717C00100000"}],
            "quotes": [{"ok": False, "option_contract": "AAPL20260717C00100000", "error": "IBKR error 10089 missing OPRA subscription"}],
            "permissions_summary": {
                "option_metadata_available": True,
                "option_quotes_available": False,
                "likely_missing_opra": True,
                "errors": ["IBKR error 10089 missing OPRA subscription"],
            },
            "warnings": ["Options final recommendations should remain blocked until option quotes are available."],
            "errors": [],
        },
    )

    result = run_provider_dry_run(
        ticker="AAPL",
        include_market_data=True,
        include_news=False,
        include_sec_filings=False,
        include_earnings_transcripts=False,
        include_options=True,
    )

    assert result["ok"] is True
    assert result["selected_providers"]["market_data_provider"] == "ibkr"
    assert result["checks"]["ibkr_connection"]["usable"] is True
    assert result["checks"]["market_data"]["provider"] == "ibkr"
    assert result["checks"]["market_data"]["data"]["data"]["quote_fallback_used"] is True
    assert result["checks"]["options"]["status"] == "unavailable"
    assert result["checks"]["options"]["data"]["data"]["metadata_available"] is True
    assert result["checks"]["options"]["data"]["data"]["option_quote_test_attempted"] is True
    assert result["checks"]["options"]["data"]["data"]["contracts_tested"] == 1
    assert result["checks"]["options"]["data"]["data"]["likely_missing_opra"] is True
    assert "blocked" in result["checks"]["options"]["error"]
    assert result["checks"]["option_risk"]["data"]["data"]["final_options_blocked_reason"]
    assert result["checks"]["option_strategy_engine"]["status"] == "unavailable"
    assert result["options_blocked_status"]["status"] in {"ready_with_warnings", "not_ready"}
