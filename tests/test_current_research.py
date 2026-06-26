import time

import pytest

import research.research_orchestrator as orchestrator
from research.research_orchestrator import build_current_research, clear_research_cache, empty_research_response


@pytest.fixture(autouse=True)
def _clear_cache_and_env(monkeypatch):
    clear_research_cache()
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setenv("RESEARCH_CACHE_TTL_SECONDS", "900")
    yield
    clear_research_cache()


def _mock_local_news(monkeypatch, calls):
    def fake_fetch_recent_news(ticker, source="ibkr_optional", limit=20, config=None):
        calls["news"] = calls.get("news", 0) + 1
        return {
            "ok": True,
            "provider": "mock",
            "available": True,
            "ticker": ticker,
            "articles": [
                {
                    "title": f"{ticker} product update",
                    "summary": f"{ticker} announced a product update.",
                    "url": f"https://investor.example.com/{ticker.lower()}/news",
                    "published_at": "2026-06-20T12:00:00Z",
                    "sentiment": "positive",
                }
            ],
            "warnings": [],
            "errors": [],
        }

    monkeypatch.setattr(orchestrator, "fetch_recent_news", fake_fetch_recent_news)


def test_missing_openai_key_uses_local_research_when_available(monkeypatch):
    calls = {}
    _mock_local_news(monkeypatch, calls)

    result = build_current_research(["AAPL"], scopes=["company_news"], provider="auto", request_id="local-1")

    assert result["ok"] is True
    assert result["status"] in {"available", "partial"}
    assert result["provider"] == "local"
    assert result["local_research_used"] is True
    assert result["web_search_used"] is False
    assert result["dossiers"][0]["ticker"] == "AAPL"
    assert result["dossiers"][0]["positive_catalysts"]
    assert result["sources"][0]["url"].startswith("https://")
    assert calls["news"] == 1


def test_all_research_unavailable_returns_stable_contract(monkeypatch):
    monkeypatch.setattr(
        orchestrator,
        "fetch_recent_news",
        lambda *args, **kwargs: {"ok": False, "articles": [], "warnings": ["News disabled."], "errors": []},
    )

    result = build_current_research(["AAPL"], scopes=["company_news"], provider="local", request_id="none-1")

    assert result["ok"] is False
    assert result["research_version"] == "current_research_v1"
    assert result["status"] == "unavailable"
    assert result["provider"] == "local"
    assert result["dossiers"][0]["status"] == "unavailable"
    assert result["usage"]["web_search_calls"] == 0
    assert set(result).issuperset(
        {
            "ok",
            "status",
            "provider",
            "dossiers",
            "sources",
            "warnings",
            "errors",
            "usage",
        }
    )


def test_cache_reuses_identical_request_within_ttl(monkeypatch):
    calls = {}
    _mock_local_news(monkeypatch, calls)

    first = build_current_research(["AAPL"], scopes=["company_news"], provider="local", request_id="cache-1", as_of="2026-06-22T12:00:00Z")
    second = build_current_research(["AAPL"], scopes=["company_news"], provider="local", request_id="cache-1", as_of="2026-06-22T12:00:00Z")

    assert first["cache_hit"] is False
    assert second["cache_hit"] is True
    assert calls["news"] == 1
    assert "sk-test" not in str(second)


def test_cache_expiry_triggers_provider_call(monkeypatch):
    calls = {}
    _mock_local_news(monkeypatch, calls)
    monkeypatch.setenv("RESEARCH_CACHE_TTL_SECONDS", "1")

    build_current_research(["AAPL"], scopes=["company_news"], provider="local", request_id="cache-2", as_of="2026-06-22T12:00:00Z")
    time.sleep(1.05)
    result = build_current_research(["AAPL"], scopes=["company_news"], provider="local", request_id="cache-2", as_of="2026-06-22T12:00:00Z")

    assert result["cache_hit"] is False
    assert calls["news"] == 2


def test_disabled_research_contract_is_stable():
    result = empty_research_response(status="disabled", provider="none", tickers=["AAPL"], scopes=["company_news"])

    assert result["ok"] is True
    assert result["status"] == "disabled"
    assert result["provider"] == "none"
    assert result["dossiers"] == []
    assert result["sources"] == []


def test_source_url_safety_and_deduplication(monkeypatch):
    def fake_fetch_recent_news(ticker, source="ibkr_optional", limit=20, config=None):
        return {
            "ok": True,
            "articles": [
                {"title": "Good", "summary": "Good source.", "url": "https://example.com/news?token=secret", "published_at": "2026-06-20", "sentiment": "neutral"},
                {"title": "Duplicate", "summary": "Duplicate source.", "url": "https://example.com/news?token=secret", "published_at": "2026-06-20", "sentiment": "neutral"},
                {"title": "Bad", "summary": "Unsafe.", "url": "javascript:alert(1)", "published_at": "2026-06-20", "sentiment": "neutral"},
            ],
            "warnings": [],
            "errors": [],
        }

    monkeypatch.setattr(orchestrator, "fetch_recent_news", fake_fetch_recent_news)

    result = build_current_research(["AAPL"], scopes=["company_news"], provider="local", request_id="urls-1")

    assert len(result["sources"]) == 1
    assert result["sources"][0]["url"] == "https://example.com/news"
    assert any("unsafe source" in warning.lower() or "malformed" in warning.lower() for warning in result["warnings"])


def test_openai_failure_falls_back_to_local(monkeypatch):
    calls = {}
    _mock_local_news(monkeypatch, calls)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setattr(orchestrator, "research_with_openai_web", lambda *args, **kwargs: {"ok": False, "web_search_used": False, "sources": [], "evidence_items": [], "warnings": ["OpenAI failed."], "errors": [], "usage": {}})

    result = build_current_research(["AAPL"], scopes=["company_news"], provider="openai", request_id="fallback-1")

    assert result["ok"] is True
    assert result["provider"] == "local"
    assert result["local_research_used"] is True
    assert any("OpenAI failed" in warning for warning in result["warnings"])
