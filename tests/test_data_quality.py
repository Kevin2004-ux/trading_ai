from quality.data_quality import (
    validate_market_data_quality,
    validate_options_chain_quality,
)


def _snapshot(*, fallback=False, stale=False):
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
            "data_freshness": {"ok": True, "age_days": 5 if stale else 1, "is_stale": stale},
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

