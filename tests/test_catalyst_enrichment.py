from datetime import datetime, timedelta, timezone

from realtime.catalyst_enrichment import (
    enrich_candidate_with_catalysts,
    get_catalyst_snapshot,
    get_earnings_snapshot,
    get_news_snapshot,
    score_catalyst_strength,
)
from tools.agent_tools import get_catalyst_brain_tool


def test_missing_api_key_returns_clean_unavailable_response(monkeypatch):
    monkeypatch.setattr("realtime.catalyst_enrichment._get_fmp_api_key", lambda: None)

    news = get_news_snapshot("AAPL")
    earnings = get_earnings_snapshot("AAPL")

    assert news["ok"] is False
    assert news["source"] == "unavailable"
    assert earnings["ok"] is False
    assert earnings["source"] == "unavailable"


def test_positive_news_keywords_produce_positive_catalyst_score():
    news_snapshot = {
        "ok": True,
        "items": [
            {"title": "Analyst upgrade and price target raise", "summary": "Strong demand and contract win", "sentiment": "positive"},
            {"title": "Product launch boosts outlook", "summary": "Record revenue expected", "sentiment": "positive"},
        ],
    }
    earnings_snapshot = {"ok": True, "days_until_earnings": 20, "is_earnings_risk": False}
    market_snapshot = {"data": {"technical_snapshot": {"relative_volume": 2.1, "daily_return": 3.0, "atr_percent": 4.0}}}

    result = score_catalyst_strength(news_snapshot, earnings_snapshot, market_snapshot)

    assert result["catalyst_label"] in {"positive", "strong_positive"}
    assert result["catalyst_score"] > 60


def test_negative_or_risk_keywords_produce_negative_or_high_risk_label():
    news_snapshot = {
        "ok": True,
        "items": [
            {"title": "SEC investigation and lawsuit expand", "summary": "Company cuts guidance after downgrade", "sentiment": "negative"},
            {"title": "Dilution offering announced", "summary": "Weak demand raises concerns", "sentiment": "negative"},
        ],
    }
    earnings_snapshot = {"ok": True, "days_until_earnings": 3, "is_earnings_risk": True}
    market_snapshot = {"data": {"technical_snapshot": {"relative_volume": 0.9, "daily_return": -4.0, "atr_percent": 8.5}}}

    result = score_catalyst_strength(news_snapshot, earnings_snapshot, market_snapshot)

    assert result["catalyst_label"] in {"negative", "high_risk"}
    assert result["risk_flags"]


def test_earnings_within_seven_days_creates_risk_flag():
    result = score_catalyst_strength(
        news_snapshot={"ok": True, "items": []},
        earnings_snapshot={"ok": True, "days_until_earnings": 5, "is_earnings_risk": True},
        market_snapshot={},
    )

    assert any("earnings" in flag.lower() for flag in result["risk_flags"])


def test_candidate_enrichment_attaches_catalyst_context(monkeypatch):
    monkeypatch.setattr(
        "realtime.catalyst_enrichment.get_news_snapshot",
        lambda ticker, lookback_days=7, max_items=10: {
            "ok": True,
            "ticker": ticker,
            "source": "fmp",
            "timestamp": "2026-06-05T00:00:00+00:00",
            "lookback_days": lookback_days,
            "items": [{"title": "Upgrade", "summary": "Contract win", "sentiment": "positive", "relevance_score": 8.0}],
            "error": None,
        },
    )
    monkeypatch.setattr(
        "realtime.catalyst_enrichment.get_earnings_snapshot",
        lambda ticker: {
            "ok": True,
            "ticker": ticker,
            "source": "fmp",
            "timestamp": "2026-06-05T00:00:00+00:00",
            "earnings_date": None,
            "days_until_earnings": 14,
            "is_earnings_risk": False,
            "error": None,
        },
    )

    candidate = {"ticker": "AAPL", "technical_snapshot": {"relative_volume": 2.0, "daily_return": 2.0, "atr_percent": 4.0}}
    enriched = enrich_candidate_with_catalysts(candidate)

    assert "catalyst_context" in enriched
    assert enriched["catalyst_context"]["catalyst_label"] in {"positive", "strong_positive"}


def test_get_catalyst_snapshot_returns_combined_structure(monkeypatch):
    monkeypatch.setattr(
        "realtime.catalyst_enrichment.get_news_snapshot",
        lambda ticker, lookback_days=7, max_items=10: {"ok": False, "ticker": ticker, "source": "unavailable", "timestamp": "x", "lookback_days": lookback_days, "items": [], "error": "no key"},
    )
    monkeypatch.setattr(
        "realtime.catalyst_enrichment.get_earnings_snapshot",
        lambda ticker: {"ok": True, "ticker": ticker, "source": "fmp", "timestamp": "x", "earnings_date": None, "days_until_earnings": 10, "is_earnings_risk": False, "error": None},
    )

    result = get_catalyst_snapshot("AAPL")

    assert result["ticker"] == "AAPL"
    assert "news_snapshot" in result["data"]
    assert "earnings_snapshot" in result["data"]
    assert "catalyst_score" in result["data"]


def test_get_catalyst_brain_tool_returns_structured_response(monkeypatch):
    monkeypatch.setattr(
        "tools.agent_tools.get_news_snapshot",
        lambda ticker, lookback_days=7: {"ok": True, "ticker": ticker, "source": "fmp", "timestamp": "x", "lookback_days": lookback_days, "items": [], "error": None},
    )
    monkeypatch.setattr(
        "tools.agent_tools.get_earnings_snapshot",
        lambda ticker: {"ok": True, "ticker": ticker, "source": "fmp", "timestamp": "x", "earnings_date": None, "days_until_earnings": 12, "is_earnings_risk": False, "error": None},
    )
    monkeypatch.setattr(
        "tools.agent_tools.get_catalyst_snapshot",
        lambda ticker, lookback_days=7: {
            "ok": True,
            "ticker": ticker,
            "source": "fmp",
            "timestamp": "x",
            "data": {
                "news_snapshot": {"ok": True},
                "earnings_snapshot": {"ok": True},
                "catalyst_score": {"catalyst_score": 72.0, "catalyst_label": "positive"},
            },
            "error": None,
        },
    )

    result = get_catalyst_brain_tool("AAPL")

    assert result["ok"] is True
    assert result["tool"] == "get_catalyst_brain_tool"
    assert result["data"]["catalyst_score"]["catalyst_label"] == "positive"
