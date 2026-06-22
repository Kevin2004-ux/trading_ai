import sqlite3

from scanner.swing_scanner import (
    build_stock_candidate,
    calculate_trade_levels,
    scan_multi_strategy_candidates,
    scan_swing_candidates,
)


def _market_snapshot(
    ticker: str,
    *,
    current_price: float = 120.0,
    sma_20: float = 114.0,
    sma_50: float = 105.0,
    sma_200: float = 100.0,
    high_20: float = 121.0,
    low_20: float = 108.0,
    atr_14: float = 4.0,
    atr_percent: float = 3.33,
    average_volume_20: float = 2_000_000,
    relative_volume: float = 1.8,
    freshness_label: str = "fresh",
) -> dict:
    return {
        "ok": True,
        "ticker": ticker,
        "source": "polygon",
        "timestamp": "2026-06-05T12:00:00+00:00",
        "error": None,
        "data": {
            "quote": {
                "last_price": current_price,
                "previous_close": current_price - 1.5,
                "day_volume": average_volume_20,
                "last_trade_timestamp": "2026-06-05T12:00:00+00:00",
            },
            "quote_error": None,
            "bars": [],
            "row_count": 180,
            "technical_snapshot": {
                "ok": True,
                "error": None,
                "current_price": current_price,
                "previous_close": current_price - 1.5,
                "daily_return": 1.2,
                "sma_20": sma_20,
                "sma_50": sma_50,
                "sma_200": sma_200,
                "rsi_14": 61.0,
                "macd": 1.5,
                "average_volume_20": average_volume_20,
                "relative_volume": relative_volume,
                "atr_14": atr_14,
                "atr_percent": atr_percent,
                "high_20": high_20,
                "low_20": low_20,
                "distance_from_20_sma": 3.2,
                "distance_from_50_sma": 7.8,
            },
            "data_freshness": {
                "ok": True,
                "error": None,
                "latest_bar_timestamp": "2026-06-05T00:00:00+00:00",
                "age_days": 0.0,
                "is_stale": False,
                "freshness_label": freshness_label,
            },
        },
    }


def _bars(start: float = 80.0, count: int = 120) -> list[dict]:
    return [
        {
            "timestamp": f"2026-01-{(index % 28) + 1:02d}T00:00:00+00:00",
            "open": start + index * 0.3,
            "high": start + index * 0.3 + 1,
            "low": start + index * 0.3 - 1,
            "close": start + index * 0.3,
            "volume": 2_000_000,
        }
        for index in range(count)
    ]


def test_scanner_handles_empty_ticker_list():
    result = scan_swing_candidates([])

    assert result["ok"] is False
    assert result["total_scanned"] == 0
    assert result["passed_candidates"] == []
    assert result["rejected_candidates"] == []
    assert result["errors"]


def test_build_stock_candidate_creates_expected_fields():
    candidate = build_stock_candidate("AAPL", _market_snapshot("AAPL"))

    assert candidate["ticker"] == "AAPL"
    assert candidate["asset_type"] == "stock"
    assert candidate["direction"] == "long"
    assert candidate["current_price"] == 120.0
    assert candidate["setup_type"] == "momentum_breakout"
    assert candidate["technical_snapshot"]["atr_14"] == 4.0
    assert candidate["data_freshness"]["freshness_label"] == "fresh"


def test_calculate_trade_levels_returns_expected_values_for_valid_data():
    levels = calculate_trade_levels(
        {
            "current_price": 120.0,
            "atr_14": 4.0,
            "sma_20": 110.0,
            "high_20": 130.0,
        }
    )

    assert levels["ok"] is True
    assert levels["entry_price"] == 120.0
    assert levels["stop_loss"] == 110.0
    assert levels["target_price"] == 132.0
    assert round(levels["risk_reward"], 2) == 1.2


def test_strong_ticker_passes_and_is_ranked(monkeypatch, tmp_path):
    monkeypatch.setattr(
        "scanner.swing_scanner.get_market_snapshot",
        lambda ticker, lookback_days=180: _market_snapshot(ticker),
    )

    result = scan_swing_candidates(["AAPL"], db_path=str(tmp_path / "scanner.db"))

    assert result["ok"] is True
    assert result["total_passed"] == 1
    assert result["total_rejected"] == 0
    assert result["passed_candidates"][0]["ticker"] == "AAPL"
    assert result["passed_candidates"][0]["rank"] == 1
    assert result["passed_candidates"][0]["recommendation_status"] in {"recommendable", "watchlist"}


def test_latest_completed_session_bar_does_not_block_stock_candidate(monkeypatch, tmp_path):
    snapshot = _market_snapshot("AAPL", freshness_label="latest_completed_session")
    snapshot["data"]["data_freshness"].update(
        {
            "latest_bar_timestamp": "2026-06-18T00:00:00+00:00",
            "age_days": 4.1,
            "is_stale": False,
            "market_session": {
                "is_latest_completed_session": True,
                "is_stale_by_session": False,
                "latest_expected_completed_session": "2026-06-18",
            },
        }
    )

    monkeypatch.setattr("scanner.swing_scanner.get_market_snapshot", lambda ticker, lookback_days=180: snapshot)

    result = scan_swing_candidates(["AAPL"], db_path=str(tmp_path / "scanner.db"))

    assert result["total_passed"] == 1
    assert result["total_rejected"] == 0
    assert result["passed_candidates"][0]["data_quality"]["quality_label"] == "good"
    assert result["passed_candidates"][0]["data_freshness"]["freshness_label"] == "latest_completed_session"


def test_scanner_includes_technical_confirmation_summary(monkeypatch, tmp_path):
    snapshot = _market_snapshot("AAPL")
    snapshot["data"]["bars"] = _bars()

    monkeypatch.setattr(
        "scanner.swing_scanner.get_market_snapshot",
        lambda ticker, lookback_days=180: snapshot,
    )

    result = scan_swing_candidates(["AAPL"], db_path=str(tmp_path / "scanner.db"))
    candidate = (result["passed_candidates"] or result["rejected_candidates"])[0]

    assert "volume_profile_confirmation" in candidate
    assert "timeframe_confirmation" in candidate
    assert "technical_confirmation_summary" in candidate
    assert candidate["technical_confirmation_summary"]["status"] in {"confirmed", "neutral", "warning", "rejected"}


def test_weak_ticker_is_rejected_and_logged(monkeypatch, tmp_path):
    weak_snapshot = _market_snapshot("TSLA", relative_volume=0.8)
    db_path = str(tmp_path / "scanner.db")

    monkeypatch.setattr(
        "scanner.swing_scanner.get_market_snapshot",
        lambda ticker, lookback_days=180: weak_snapshot,
    )

    result = scan_swing_candidates(["TSLA"], db_path=db_path)

    assert result["total_passed"] == 0
    assert result["total_rejected"] == 1
    assert result["rejected_candidates"][0]["ticker"] == "TSLA"
    assert "minimum_relative_volume" in result["rejected_candidates"][0]["failed_constraints"]

    with sqlite3.connect(db_path) as conn:
        count = conn.execute("SELECT COUNT(*) FROM candidate_evaluations").fetchone()[0]
    assert count == 1


def test_failed_market_data_response_becomes_rejected_candidate(monkeypatch, tmp_path):
    monkeypatch.setattr(
        "scanner.swing_scanner.get_market_snapshot",
        lambda ticker, lookback_days=180: {
            "ok": False,
            "ticker": ticker,
            "source": "polygon",
            "timestamp": "2026-06-05T12:00:00+00:00",
            "data": None,
            "error": "Ticker not found.",
        },
    )

    result = scan_swing_candidates(["BAD"], db_path=str(tmp_path / "scanner.db"))

    assert result["total_passed"] == 0
    assert result["total_rejected"] == 1
    assert result["rejected_candidates"][0]["ticker"] == "BAD"
    assert result["rejected_candidates"][0]["rejection_reason"] == "Ticker not found."


def test_scan_logs_scanner_run_and_candidate_evaluations(monkeypatch, tmp_path):
    snapshots = {
        "AAPL": _market_snapshot("AAPL"),
        "MSFT": _market_snapshot("MSFT", current_price=118.0, relative_volume=1.35, high_20=121.0),
        "WEAK": _market_snapshot("WEAK", current_price=90.0, sma_20=95.0, sma_50=100.0, relative_volume=0.7),
    }
    db_path = str(tmp_path / "scanner.db")

    def fake_market_snapshot(ticker, lookback_days=180):
        return snapshots[ticker]

    monkeypatch.setattr("scanner.swing_scanner.get_market_snapshot", fake_market_snapshot)

    result = scan_swing_candidates(["AAPL", "MSFT", "WEAK"], universe="test_universe", db_path=db_path)

    assert result["scanner_run_id"] is not None
    assert result["total_scanned"] == 3
    assert result["total_passed"] == 2
    assert result["total_rejected"] == 1
    assert len(result["passed_candidates"]) == 2
    assert len(result["rejected_candidates"]) == 1
    assert result["passed_candidates"][0]["score"] >= result["passed_candidates"][1]["score"]

    with sqlite3.connect(db_path) as conn:
        scanner_run_count = conn.execute("SELECT COUNT(*) FROM scanner_runs").fetchone()[0]
        candidate_count = conn.execute("SELECT COUNT(*) FROM candidate_evaluations").fetchone()[0]
        totals = conn.execute(
            "SELECT total_scanned, total_passed, total_rejected FROM scanner_runs WHERE id = ?",
            (result["scanner_run_id"],),
        ).fetchone()

    assert scanner_run_count == 1
    assert candidate_count == 3
    assert totals == (3, 2, 1)


def test_multi_strategy_scan_fetches_failed_ticker_once_and_returns_json(monkeypatch, tmp_path):
    calls = {"BRK.B": 0, "AAPL": 0}

    def fake_market_snapshot(ticker, lookback_days=180):
        calls[ticker] = calls.get(ticker, 0) + 1
        if ticker == "BRK.B":
            return {
                "ok": False,
                "ticker": ticker,
                "source": "ibkr",
                "data": None,
                "error": "IBKR could not qualify stock contract for BRK.B using symbol BRK B.",
                "error_type": "symbol",
            }
        return _market_snapshot(ticker)

    monkeypatch.setattr("scanner.swing_scanner.get_market_snapshot", fake_market_snapshot)

    result = scan_multi_strategy_candidates(
        ["BRK.B", "AAPL"],
        profiles=["momentum_breakout", "trend_pullback"],
        db_path=str(tmp_path / "scanner.db"),
    )

    assert result["ok"] is True
    assert calls["BRK.B"] == 1
    assert calls["AAPL"] == 1
    assert result["total_tickers_scanned"] == 2
    assert result["scan_execution_summary"]["total_tickers"] == 2
    assert result["scan_execution_summary"]["completed_tickers"] == 2
    assert any(candidate["ticker"] == "BRK.B" for candidate in result["rejected_candidates"])
    assert result["data_quality_summary"]["counts"]["unavailable"] >= 1


def test_multi_strategy_scan_preserves_schema_with_async_failure(monkeypatch, tmp_path):
    monkeypatch.setattr(
        "scanner.swing_scanner.run_async_scan_tickers",
        lambda *args, **kwargs: {
            "ok": True,
            "completed": False,
            "total_tickers": 2,
            "completed_tickers": 1,
            "failed_tickers": ["BAD"],
            "timed_out_tickers": [],
            "results": [
                {"ok": True, "ticker": "AAPL", "result": _market_snapshot("AAPL")},
                {"ok": False, "ticker": "BAD", "error_type": "market_data", "error": "Provider failed."},
            ],
            "errors": [{"ticker": "BAD", "type": "failure", "message": "Provider failed."}],
            "warnings": ["Scan completed with partial results due to timeout or provider failures."],
            "duration_seconds": 0.2,
        },
    )

    result = scan_multi_strategy_candidates(
        ["AAPL", "BAD"],
        profiles=["momentum_breakout"],
        db_path=str(tmp_path / "scanner.db"),
    )

    assert result["ok"] is True
    assert result["scan_execution_summary"]["partial_results_used"] is True
    assert result["scan_execution_summary"]["failed_tickers"] == ["BAD"]
    assert any(candidate["ticker"] == "BAD" for candidate in result["rejected_candidates"])
    assert "best_candidates" in result
    assert "watchlist_candidates" in result


def test_multi_strategy_scan_blocks_stale_fallback(monkeypatch, tmp_path):
    stale_snapshot = _market_snapshot("WMT")
    stale_snapshot["data"]["quote"]["quote_source"] = "historical_bar_fallback"
    stale_snapshot["data"]["quote_fallback_used"] = True
    stale_snapshot["data"]["data_freshness"]["age_days"] = 10
    stale_snapshot["data"]["data_freshness"]["is_stale"] = True
    stale_snapshot["data"]["data_quality"] = {
        "ok": False,
        "quality_label": "poor",
        "price_source": "historical_bar_fallback",
        "quote_status": "unavailable",
        "final_recommendation_allowed": False,
        "warnings": ["IBKR live quote unavailable; using latest historical close."],
        "errors": ["Latest historical bar is stale."],
    }

    monkeypatch.setattr("scanner.swing_scanner.get_market_snapshot", lambda ticker, lookback_days=180: stale_snapshot)

    result = scan_multi_strategy_candidates(
        ["WMT"],
        profiles=["momentum_breakout"],
        db_path=str(tmp_path / "scanner.db"),
    )

    assert result["total_recommendable"] == 0
    assert result["total_watchlist"] == 0
    assert result["rejected_candidates"][0]["failed_constraints"] == ["data_quality"]
    assert "stale" in result["rejected_candidates"][0]["rejection_reason"].lower()


def test_sec_filing_critical_risk_rejects_candidate(monkeypatch, tmp_path):
    monkeypatch.setattr("scanner.swing_scanner.get_market_snapshot", lambda ticker, lookback_days=180: _market_snapshot(ticker))
    monkeypatch.setattr(
        "scanner.swing_scanner.fetch_recent_filings",
        lambda *args, **kwargs: {
            "ok": True,
            "filings": [
                {
                    "accession_number": "0001",
                    "form": "8-K",
                    "filing_date": "2026-06-01",
                    "description": "Non-reliance and restatement of prior financial statements",
                    "items": ["4.02"],
                    "filing_url": None,
                }
            ],
            "warnings": [],
            "errors": [],
        },
    )

    result = scan_swing_candidates(
        ["AAPL"],
        db_path=str(tmp_path / "scanner.db"),
        config={"sec_research_enabled": True},
    )

    assert result["total_passed"] == 0
    assert result["total_rejected"] == 1
    candidate = result["rejected_candidates"][0]
    assert candidate["filing_sentiment"]["trade_impact"] == "blocking"
    assert "critical_filing_risk" in candidate["failed_constraints"]


def test_extreme_short_interest_downgrades_weak_long_candidate(monkeypatch, tmp_path):
    weak_snapshot = _market_snapshot("AAPL", current_price=116.0, high_20=140.0, relative_volume=0.9)
    monkeypatch.setattr("scanner.swing_scanner.get_market_snapshot", lambda ticker, lookback_days=180: weak_snapshot)

    result = scan_swing_candidates(
        ["AAPL"],
        db_path=str(tmp_path / "scanner.db"),
        config={
            "short_data": {"AAPL": {"short_interest_percent_float": 32.0, "days_to_cover": 8.0}},
            "short_interest_enabled": True,
        },
    )

    candidate = (result["passed_candidates"] or result["rejected_candidates"])[0]
    assert candidate["short_interest"]["short_interest_level"] == "extreme"
    assert candidate["short_interest"]["trade_impact"] == "caution"
    assert candidate["recommendation_status"] in {"watchlist", "rejected"}


def test_critical_news_risk_rejects_candidate(monkeypatch, tmp_path):
    monkeypatch.setattr("scanner.swing_scanner.get_market_snapshot", lambda ticker, lookback_days=180: _market_snapshot(ticker))
    monkeypatch.setattr(
        "scanner.swing_scanner.fetch_recent_news",
        lambda *args, **kwargs: {
            "ok": True,
            "available": True,
            "articles": [{"headline": "AAPL announces accounting issue and restatement", "summary": ""}],
            "warnings": [],
            "errors": [],
        },
    )

    result = scan_swing_candidates(
        ["AAPL"],
        db_path=str(tmp_path / "scanner.db"),
        config={"news_research_enabled": True},
    )

    assert result["total_passed"] == 0
    candidate = result["rejected_candidates"][0]
    assert candidate["news_sentiment"]["trade_impact"] == "blocking"
    assert "critical_news_risk" in candidate["failed_constraints"]
