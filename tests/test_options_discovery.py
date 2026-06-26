from scanner.options_discovery import discover_option_ideas, empty_option_discovery_response


def _stock(ticker="AAPL", status="watchlist", score=82.0, direction="long"):
    return {
        "ticker": ticker,
        "asset_type": "stock",
        "direction": direction,
        "recommendation_status": status,
        "opportunity_score": score,
        "score": score - 5,
        "current_price": 120.0,
        "entry_price": 120.0,
        "target_price": 135.0 if direction != "short" else 105.0,
        "stop_loss": 114.0 if direction != "short" else 128.0,
        "risk_reward": 2.4,
        "technical_snapshot": {"current_price": 120.0, "sma_20": 118.0, "relative_volume": 1.4},
        "data_quality": {"ok": True, "quality_label": "good", "errors": [], "warnings": []},
        "why_ranked": [f"{ticker} was a deterministic near-miss."],
    }


def _provider_failure(ticker="BAD"):
    return {
        "ticker": ticker,
        "asset_type": "stock",
        "recommendation_status": "rejected",
        "current_price": None,
        "technical_snapshot": {},
        "failed_constraints": ["scanner_error"],
        "data_quality": {"ok": False, "quality_label": "unavailable", "errors": ["provider unavailable"], "warnings": []},
    }


def _chain(ticker="AAPL", *, metadata_only=False, include_puts=True):
    call = {
        "option_contract": f"{ticker}260717C00125000",
        "underlying_ticker": ticker,
        "option_type": "call",
        "strike": 125.0,
        "expiration": "2026-07-17",
        "days_to_expiration": 25,
        "bid": None if metadata_only else 3.8,
        "ask": None if metadata_only else 4.0,
        "mid": None if metadata_only else 3.9,
        "volume": 450,
        "open_interest": 1800,
        "implied_volatility": 0.3,
        "iv_rank": 35,
        "delta": 0.52,
        "gamma": 0.04,
        "theta": -0.04,
        "vega": 0.12,
    }
    put = {
        **call,
        "option_contract": f"{ticker}260717P00115000",
        "option_type": "put",
        "strike": 115.0,
        "bid": None if metadata_only else 2.8,
        "ask": None if metadata_only else 3.0,
        "mid": None if metadata_only else 2.9,
        "delta": -0.42,
    }
    rows = [call]
    if include_puts:
        rows.append(put)
    return {"ok": True, "ticker": ticker, "data": {"contracts": rows}, "error": None}


def test_empty_option_discovery_response_has_stable_contract():
    result = empty_option_discovery_response()

    assert result["discovery_version"] == "option_discovery_v1"
    assert result["status"] == "disabled"
    assert result["paper_eligible_contracts"] == []
    assert result["underlying_watchlist"] == []


def test_independent_discovery_uses_non_final_stock_near_misses(monkeypatch):
    calls = []

    def fake_chain(ticker, **kwargs):
        calls.append(ticker)
        return _chain(ticker)

    monkeypatch.setattr("scanner.options_discovery.get_options_chain", fake_chain)

    result = discover_option_ideas(
        [_provider_failure("BAD"), _stock("AAPL", "watchlist", 82.0), _stock("NVDA", "rejected", 88.0)],
        runtime_context={"requested": True, "safe_to_run_options": False},
        max_underlyings=2,
        max_contracts_per_ticker=2,
    )

    assert result["status"] in {"available", "partial"}
    assert calls == ["NVDA", "AAPL"]
    assert [row["ticker"] for row in result["underlying_shortlist"]] == ["NVDA", "AAPL"]
    assert result["research_only_contracts"] or result["blocked_contracts"]
    assert all(row["underlying_status"] in {"watchlist", "blocked"} for row in result["underlying_shortlist"])
    assert result["options_final_eligibility"] is False


def test_metadata_only_chain_returns_underlying_watchlist_not_exact_contracts(monkeypatch):
    monkeypatch.setattr("scanner.options_discovery.get_options_chain", lambda ticker, **kwargs: _chain(ticker, metadata_only=True))

    result = discover_option_ideas([_stock("AAPL")], runtime_context={"requested": True}, max_underlyings=1)

    assert result["paper_eligible_contracts"] == []
    assert result["research_only_contracts"] == []
    assert result["blocked_contracts"] == []
    assert result["underlying_watchlist"]
    assert "bid/ask" in result["underlying_watchlist"][0]["required_before_contract_ranking"]


def test_provider_unavailable_has_no_exact_ranking_and_deduped_error(monkeypatch):
    monkeypatch.setattr(
        "scanner.options_discovery.get_options_chain",
        lambda ticker, **kwargs: {"ok": False, "ticker": ticker, "error": "IBKR option quotes unavailable: OPRA permission missing.", "data": None},
    )

    result = discover_option_ideas([_stock("AAPL"), _stock("MSFT")], runtime_context={"requested": True})

    assert result["status"] == "unavailable"
    assert result["paper_eligible_contracts"] == []
    assert result["research_only_contracts"] == []
    assert result["blocked_contracts"] == []
    assert result["errors"].count("IBKR option quotes unavailable: OPRA permission missing.") == 1
    assert any("OPRA" in item for item in result["missing_requirements"])


def test_bearish_underlying_is_not_forced_into_long_calls(monkeypatch):
    monkeypatch.setattr("scanner.options_discovery.get_options_chain", lambda ticker, **kwargs: _chain(ticker, include_puts=True))

    result = discover_option_ideas([_stock("AAPL", direction="short")], runtime_context={"requested": True}, max_underlyings=1)
    exact = result["research_only_contracts"] + result["blocked_contracts"] + result["paper_eligible_contracts"]

    assert exact
    assert all(row["option_type"] == "put" for row in exact)
    assert all(row["strategy"] != "long_call" for row in exact)


def test_explicit_ticker_review_only_researches_requested_ticker(monkeypatch):
    calls = []

    def fake_chain(ticker, **kwargs):
        calls.append(ticker)
        return _chain(ticker)

    monkeypatch.setattr("scanner.options_discovery.get_options_chain", fake_chain)

    result = discover_option_ideas(
        [_stock("AAPL", score=70), _stock("MSFT", score=99)],
        explicit_tickers=["AAPL"],
        runtime_context={"requested": True},
    )

    assert calls == ["AAPL"]
    assert [row["ticker"] for row in result["underlying_shortlist"]] == ["AAPL"]
