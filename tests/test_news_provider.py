from research import news_provider
from research.news_provider import diagnose_news_provider, fetch_recent_news


def test_news_provider_unavailable_when_disabled():
    result = fetch_recent_news("AAPL", config={"NEWS_RESEARCH_ENABLED": "false"})

    assert result["ok"] is False
    assert result["available"] is False
    assert result["warnings"]


def test_news_provider_requires_explicit_ibkr_diagnostic():
    result = fetch_recent_news("AAPL", config={"NEWS_RESEARCH_ENABLED": "true", "IBKR_NEWS_DIAGNOSTIC_ENABLED": "false"})

    assert result["ok"] is False
    assert "opt-in" in result["warnings"][0]


def test_news_provider_can_be_mocked(monkeypatch):
    def fake_fetch(symbol, limit=20, read_only=True):
        return {
            "ok": True,
            "articles": [
                {
                    "published_at": "2026-06-01T00:00:00+00:00",
                    "source": "IBKR",
                    "headline": "AAPL analyst upgrade",
                    "summary": "",
                    "url": "",
                    "symbols": ["AAPL"],
                }
            ],
            "warnings": [],
            "errors": [],
        }

    monkeypatch.setattr("providers.ibkr_provider.fetch_ibkr_news", fake_fetch, raising=False)

    result = fetch_recent_news("AAPL", config={"NEWS_RESEARCH_ENABLED": "true", "IBKR_NEWS_DIAGNOSTIC_ENABLED": "true"})

    assert result["ok"] is True
    assert result["available"] is True
    assert result["articles"][0]["headline"] == "AAPL analyst upgrade"


def test_diagnose_news_provider_unavailable_cleanly():
    result = diagnose_news_provider({"NEWS_RESEARCH_ENABLED": "false"})

    assert result["ok"] is False
    assert result["available"] is False
    assert result["warnings"]

