from research.earnings_8k_analyzer import analyze_earnings_8k, extract_earnings_release_sections


def test_extract_earnings_release_sections_detects_earnings_and_guidance():
    text = "The company reported earnings and revenue growth. Management raised guidance for the year."

    result = extract_earnings_release_sections(text)

    assert result["ok"] is True
    assert result["earnings_detected"] is True
    assert result["guidance_detected"] is True
    assert result["key_sections"]


def test_analyze_earnings_8k_positive_language():
    filing = {"form": "8-K", "filing_date": "2026-06-01", "items": ["2.02"]}
    text = "Financial results exceeded expectations with record revenue, improved margin, and raised guidance."

    result = analyze_earnings_8k("AAPL", filing, text)

    assert result["ok"] is True
    assert result["sentiment_label"] == "positive"
    assert "record" in result["positive_flags"]
    assert result["confidence"] > 0.5


def test_analyze_earnings_8k_negative_language():
    filing = {"form": "8-K", "filing_date": "2026-06-01", "items": ["2.02"]}
    text = "Revenue declined because of weak demand and cost pressure. Management lowered guidance."

    result = analyze_earnings_8k("AAPL", filing, text)

    assert result["sentiment_label"] == "negative"
    assert "weak demand" in result["risk_flags"]


def test_analyze_earnings_8k_requires_text():
    result = analyze_earnings_8k("AAPL", {"form": "8-K"}, "")

    assert result["ok"] is False
    assert result["sentiment_label"] == "unknown"
    assert result["errors"]

