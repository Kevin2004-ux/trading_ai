from research.earnings_transcripts import (
    analyze_guidance_context,
    analyze_transcript_sentiment,
    get_earnings_transcript_snapshot,
    normalize_transcript_item,
    score_earnings_quality,
)


def _transcript(
    content: str,
    *,
    ticker: str = "AAPL",
    year: int = 2026,
    quarter: int = 1,
) -> dict:
    return {
        "symbol": ticker,
        "year": year,
        "quarter": quarter,
        "date": "2026-05-01",
        "title": f"{ticker} earnings call",
        "content": content,
        "source": "mock",
    }


def test_positive_transcript_signals_produce_strong_earnings_quality():
    transcripts = [
        _transcript(
            "We raised guidance, saw strong demand, margin expansion, revenue acceleration, backlog strength, and excellent cost discipline."
        )
    ]

    sentiment = analyze_transcript_sentiment(transcripts)
    guidance = analyze_guidance_context(transcripts)
    quality = score_earnings_quality(sentiment, guidance)

    assert sentiment["management_tone"] == "positive"
    assert guidance["guidance_label"] == "raised"
    assert quality["earnings_quality_label"] == "strong"
    assert quality["earnings_quality_score"] >= 68


def test_lowered_guidance_and_margin_pressure_produce_weak_quality():
    transcripts = [
        _transcript(
            "We lowered guidance due to weak demand, margin pressure, pricing pressure, and a cautious tone around macro headwinds."
        )
    ]

    sentiment = analyze_transcript_sentiment(transcripts)
    guidance = analyze_guidance_context(transcripts)
    quality = score_earnings_quality(sentiment, guidance)

    assert guidance["guidance_label"] == "lowered"
    assert quality["earnings_quality_label"] == "weak"
    assert any("guidance" in item.lower() for item in quality["negative_signals"])


def test_mixed_transcript_returns_mixed():
    transcripts = [
        _transcript(
            "Demand improved in AI workloads, but management remains cautious and highlighted pricing pressure plus delayed deals."
        )
    ]

    sentiment = analyze_transcript_sentiment(transcripts)
    guidance = analyze_guidance_context(transcripts)
    quality = score_earnings_quality(sentiment, guidance)

    assert sentiment["management_tone"] in {"cautious", "neutral"}
    assert quality["earnings_quality_label"] == "mixed"


def test_unavailable_provider_returns_clean_response(monkeypatch):
    monkeypatch.setattr("research.earnings_transcripts._get_fmp_api_key", lambda: None)

    result = get_earnings_transcript_snapshot("AAPL")

    assert result["ok"] is False
    assert result["source"] == "unavailable"
    assert "not configured" in result["error"].lower()


def test_guidance_context_detects_raised_lowered_and_unclear():
    raised = analyze_guidance_context([_transcript("We raised guidance and increased outlook.")])
    lowered = analyze_guidance_context([_transcript("We lowered guidance and withdrew the prior outlook.")])
    unclear = analyze_guidance_context([_transcript("We discussed results but gave no formal outlook changes.")])

    assert raised["guidance_label"] == "raised"
    assert lowered["guidance_label"] == "lowered"
    assert unclear["guidance_label"] == "unclear"


def test_normalize_transcript_item_preserves_expected_fields():
    result = normalize_transcript_item(_transcript("Strong demand and raised guidance."))

    assert result["ticker"] == "AAPL"
    assert result["year"] == 2026
    assert result["quarter"] == 1
    assert result["reported_at"] is not None
    assert result["source"] == "mock"
