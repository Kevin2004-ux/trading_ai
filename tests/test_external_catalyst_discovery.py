from discovery import discover_external_catalyst_candidates
from discovery.catalyst_providers import StaticCatalystProvider
from discovery.candidate_discovery import discover_candidates


def test_external_provider_missing_config_warns_without_failing(monkeypatch):
    monkeypatch.delenv("EXTERNAL_CATALYST_DISCOVERY_ENABLED", raising=False)
    monkeypatch.delenv("EXTERNAL_CATALYST_SEC_ENABLED", raising=False)
    monkeypatch.delenv("FMP_API_KEY", raising=False)
    monkeypatch.delenv("SEC_USER_AGENT", raising=False)

    result = discover_external_catalyst_candidates(
        max_tickers=5,
        discovered_at="2026-06-28T12:00:00+00:00",
        seed_tickers=["AAPL", "MSFT"],
    )

    assert result["ok"] is True
    assert result["candidates"] == []
    assert result["external_discovery_used"] is False
    assert result["requires_live_validation"] is True
    assert any("disabled" in warning.lower() or "not configured" in warning.lower() for warning in result["warnings"])


def test_static_external_provider_returns_live_validation_only_candidates():
    provider = StaticCatalystProvider(
        [
            {
                "ticker": "AAPL",
                "source": "test_news",
                "catalyst_type": "earnings",
                "headline": "AAPL earnings this week",
                "url": "https://example.com/aapl",
                "published_at": "2026-06-28T10:00:00+00:00",
                "discovery_score": 91,
                "reason_discovered": "Upcoming earnings catalyst.",
            }
        ]
    )

    result = discover_external_catalyst_candidates(
        max_tickers=5,
        discovered_at="2026-06-28T12:00:00+00:00",
        intent_constraints={"catalyst_types": ["earnings"], "require_upcoming_earnings": True},
        providers=[provider],
    )

    assert result["ok"] is True
    assert result["external_discovery_used"] is True
    assert result["catalyst_types"] == ["earnings"]
    candidate = result["candidates"][0]
    assert candidate["ticker"] == "AAPL"
    assert candidate["source_type"] == "external_catalyst"
    assert candidate["requires_live_validation"] is True
    assert "opportunity_score" not in candidate
    assert "recommendation_status" not in candidate


def test_external_candidates_merge_and_dedupe_with_internal_sources(monkeypatch):
    provider = StaticCatalystProvider(
        [
            {
                "ticker": "AAPL",
                "source": "test_news",
                "catalyst_type": "news",
                "headline": "AAPL product catalyst",
                "discovery_score": 90,
            },
            {
                "ticker": "MSFT",
                "source": "test_news",
                "catalyst_type": "filings",
                "headline": "MSFT filing catalyst",
                "discovery_score": 89,
            },
        ]
    )
    monkeypatch.setattr(
        "discovery.candidate_discovery.discover_external_catalyst_candidates",
        lambda **kwargs: discover_external_catalyst_candidates(**kwargs, providers=[provider]),
    )

    result = discover_candidates(
        requested_sources=["external_catalyst", "manual_hotlist"],
        max_tickers=5,
        discovered_at="2026-06-28T12:00:00+00:00",
        intent_constraints={"catalyst_types": ["news"]},
        seed_tickers=["AAPL", "MSFT"],
    )

    assert result["ok"] is True
    assert result["external_discovery_used"] is True
    assert result["catalyst_sources_used"] == ["test_news"]
    assert result["catalyst_types"] == ["news", "filings"]
    assert result["tickers"] == ["AAPL", "MSFT"]
    assert result["candidates"][0]["sources"] == ["external_catalyst"]
    assert "opportunity_score" not in result["candidates"][0]
