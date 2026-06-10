from diagnostics import live_dry_run
from diagnostics.live_dry_run import run_provider_dry_run


def test_provider_dry_run_returns_unavailable_cleanly_when_api_keys_missing(monkeypatch):
    monkeypatch.setattr(live_dry_run, "_env_or_config", lambda name: None)
    monkeypatch.setattr(live_dry_run, "get_selected_market_data_provider", lambda: "polygon")
    monkeypatch.setattr(live_dry_run, "get_selected_options_data_provider", lambda: "polygon")

    result = run_provider_dry_run(ticker="AAPL", include_memory=True)

    assert result["ok"] is True
    assert result["ticker"] == "AAPL"
    assert result["checks"]["market_data"]["status"] == "unavailable"
    assert result["checks"]["news"]["status"] == "unavailable"
    assert result["checks"]["options"]["status"] == "unavailable"
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
        live_dry_run,
        "get_options_chain",
        lambda ticker: {
            "ok": False,
            "ticker": ticker,
            "source": "ibkr",
            "data": {"contracts": [], "row_count": 0},
            "error": "IBKR option chain metadata is reachable, but full option quote chains are not enabled yet.",
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
