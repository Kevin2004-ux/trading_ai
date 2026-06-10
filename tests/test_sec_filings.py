from research.sec_filings import (
    analyze_filing_risks,
    get_sec_filing_snapshot,
    normalize_filing_item,
    score_filing_risk,
)


def test_normalize_filing_item_produces_expected_schema():
    result = normalize_filing_item(
        {
            "symbol": "AAPL",
            "formType": "8-K",
            "acceptedDate": "2026-06-01",
            "periodOfReport": "2026-03-31",
            "title": "Current report on partnership and buyback",
            "summary": "The company announced a strategic partnership and expanded its share repurchase program.",
            "finalLink": "https://example.com/filing",
            "source": "mock",
        }
    )

    assert result["ticker"] == "AAPL"
    assert result["filing_type"] == "8-K"
    assert result["filed_at"] is not None
    assert result["url"] == "https://example.com/filing"
    assert "strategic_partnership" in result["event_keywords"]
    assert result["source"] == "mock"


def test_dilution_and_offering_keywords_create_high_filing_risk():
    result = analyze_filing_risks(
        [
            {
                "symbol": "TSLA",
                "formType": "424B5",
                "acceptedDate": "2026-06-02",
                "title": "424B5 prospectus supplement",
                "summary": "The company announced an at-the-market offering and shelf registration that may cause dilution.",
                "source": "mock",
            }
        ]
    )

    assert result["ok"] is True
    assert result["filing_risk_label"] == "high"
    assert any("dilution" in item.lower() or "offering" in item.lower() for item in result["negative_filing_signals"])
    assert result["risk_flags"]


def test_material_weakness_and_litigation_create_risk_flags():
    result = analyze_filing_risks(
        [
            {
                "symbol": "MSFT",
                "formType": "10-Q",
                "acceptedDate": "2026-05-20",
                "title": "Quarterly report",
                "summary": "Management disclosed a material weakness and ongoing litigation tied to a regulatory investigation.",
                "source": "mock",
            }
        ]
    )

    assert result["ok"] is True
    assert any("material weakness" in item.lower() for item in result["risk_flags"])
    assert any("litigation" in item.lower() or "investigation" in item.lower() for item in result["negative_filing_signals"])


def test_positive_filing_signals_are_recognized():
    result = analyze_filing_risks(
        [
            {
                "symbol": "NVDA",
                "formType": "8-K",
                "acceptedDate": "2026-05-15",
                "title": "Strategic partnership and contract award",
                "summary": "The company disclosed a strategic partnership, major contract award, and share repurchase program.",
                "source": "mock",
            }
        ]
    )

    assert result["ok"] is True
    assert result["positive_filing_signals"]
    assert result["filing_risk_label"] in {"low", "medium"}


def test_unavailable_provider_returns_clean_response(monkeypatch):
    monkeypatch.setattr("research.sec_filings._get_fmp_api_key", lambda: None)

    result = get_sec_filing_snapshot("AAPL")

    assert result["ok"] is False
    assert result["source"] == "unavailable"
    assert "not configured" in result["error"].lower()


def test_score_filing_risk_works_for_empty_and_high_risk_inputs():
    unavailable = score_filing_risk({"ticker": "AAPL", "filings_analyzed": 0, "sources": []})
    high_risk = score_filing_risk(
        {
            "ticker": "AAPL",
            "filings_analyzed": 2,
            "negative_categories": {
                "dilution_offering": {"score": 34.0},
                "material_weakness": {"score": 30.0},
            },
            "positive_categories": {},
            "positive_filing_signals": [],
            "negative_filing_signals": ["Potential dilution or offering activity."],
            "risk_flags": ["Recent filing language suggests dilution or offering risk."],
            "recent_material_events": ["8-K: Offering"],
            "sources": ["mock"],
        }
    )

    assert unavailable["filing_risk_label"] == "unavailable"
    assert high_risk["ok"] is True
    assert high_risk["filing_risk_label"] == "high"
    assert high_risk["filing_risk_score"] >= 70
