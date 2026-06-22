from quality.data_quality import (
    validate_market_data_quality,
    validate_options_chain_quality,
)


def _snapshot(*, fallback=False, stale=False, freshness_label=None, market_session=None, age_days=None):
    return {
        "ok": True,
        "ticker": "AAPL",
        "data": {
            "quote": {
                "last_price": 100.0,
                "quote_source": "historical_bar_fallback" if fallback else "ibkr",
            },
            "quote_fallback_used": fallback,
            "technical_snapshot": {"ok": True, "current_price": 100.0},
            "data_freshness": {
                "ok": True,
                "age_days": age_days if age_days is not None else 5 if stale else 1,
                "is_stale": stale,
                "freshness_label": freshness_label or ("stale" if stale else "fresh"),
                "market_session": market_session,
            },
            "data_quality_warnings": [],
        },
        "error": None,
    }


def test_live_quote_and_fresh_bars_are_good():
    result = validate_market_data_quality(_snapshot())

    assert result["quality_label"] == "good"
    assert result["quote_status"] == "available"
    assert result["final_recommendation_allowed"] is True


def test_historical_fallback_is_usable_with_warnings():
    result = validate_market_data_quality(_snapshot(fallback=True))

    assert result["quality_label"] == "usable_with_warnings"
    assert result["price_source"] == "historical_bar_fallback"
    assert result["quote_status"] == "unavailable"
    assert any("latest historical close" in warning for warning in result["warnings"])


def test_stale_fallback_blocks_final_recommendation():
    result = validate_market_data_quality(_snapshot(fallback=True, stale=True), max_stale_days=3)

    assert result["quality_label"] == "poor"
    assert result["final_recommendation_allowed"] is False
    assert any("stale" in error.lower() for error in result["errors"])


def test_latest_completed_session_not_blocked_by_calendar_age():
    result = validate_market_data_quality(
        _snapshot(
            age_days=4.1,
            freshness_label="latest_completed_session",
            market_session={
                "is_latest_completed_session": True,
                "is_stale_by_session": False,
                "latest_expected_completed_session": "2026-06-18",
            },
        ),
        max_stale_days=3,
    )

    assert result["quality_label"] == "good"
    assert result["final_recommendation_allowed"] is True
    assert not result["errors"]
    assert any("latest completed market session" in warning for warning in result["warnings"])


def test_historical_fallback_latest_completed_session_is_usable_with_warnings():
    result = validate_market_data_quality(
        _snapshot(
            fallback=True,
            age_days=4.1,
            freshness_label="latest_completed_session",
            market_session={
                "is_latest_completed_session": True,
                "is_stale_by_session": False,
                "latest_expected_completed_session": "2026-06-18",
            },
        ),
        max_stale_days=3,
    )

    assert result["quality_label"] == "usable_with_warnings"
    assert result["final_recommendation_allowed"] is True
    assert not any("stale" in error.lower() for error in result["errors"])


def test_data_quality_blocks_when_bar_is_older_than_expected_session():
    result = validate_market_data_quality(
        _snapshot(
            age_days=4.1,
            freshness_label="stale",
            market_session={
                "is_latest_completed_session": False,
                "is_stale_by_session": True,
                "latest_expected_completed_session": "2026-06-18",
            },
        ),
        max_stale_days=3,
    )

    assert result["quality_label"] == "poor"
    assert result["final_recommendation_allowed"] is False
    assert any("stale" in error.lower() for error in result["errors"])


def test_live_quote_required_blocks_fallback(monkeypatch):
    monkeypatch.setattr("config.ALLOW_LIVE_QUOTE_REQUIRED", "true", raising=False)

    result = validate_market_data_quality(_snapshot(fallback=True))

    assert result["final_recommendation_allowed"] is False
    assert any("fallback" in error.lower() for error in result["errors"])


def test_failed_provider_is_unavailable():
    result = validate_market_data_quality({"ok": False, "error": "provider timeout"})

    assert result["quality_label"] == "unavailable"
    assert result["final_recommendation_allowed"] is False
    assert "provider timeout" in result["errors"]


def test_options_without_quotes_are_blocked():
    result = validate_options_chain_quality(
        {
            "ok": False,
            "data": {"diagnostic": {"permissions_summary": {"likely_missing_opra": True}}},
            "error": "options unavailable",
        }
    )

    assert result["ok"] is False
    assert result["final_recommendation_allowed"] is False
    assert any("OPRA" in error for error in result["errors"])
