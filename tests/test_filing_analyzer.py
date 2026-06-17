from research.filing_analyzer import analyze_recent_filings, classify_filing_importance, detect_material_event_flags


def test_classify_filing_importance_marks_8k_high():
    result = classify_filing_importance({"form": "8-K"})

    assert result["ok"] is True
    assert result["importance"] == "high"
    assert result["importance_score"] == 80


def test_detect_material_event_flags_finds_earnings_and_guidance():
    filing = {"form": "8-K", "description": "Earnings release with raised guidance", "items": ["2.02", "9.01"]}

    result = detect_material_event_flags(filing)

    assert "earnings release" in result["material_events"]
    assert "guidance update" in result["material_events"]
    assert "positive earnings" in result["positive_flags"]


def test_analyze_recent_filings_detects_high_risk_departure():
    filings = [
        {
            "form": "8-K",
            "description": "Chief Financial Officer resigned and the company announced a restructuring",
            "items": ["5.02"],
        }
    ]

    result = analyze_recent_filings("AAPL", filings)

    assert result["ok"] is True
    assert result["filing_risk_level"] == "high"
    assert "CEO/CFO departure" in result["risk_flags"]


def test_analyze_recent_filings_detects_critical_restatement():
    filings = [{"form": "8-K", "description": "Non-reliance and restatement of prior financial statements", "items": ["4.02"]}]

    result = analyze_recent_filings("AAPL", filings)

    assert result["filing_risk_level"] == "critical"
    assert "restatement/amendment" in result["risk_flags"]


def test_analyze_recent_filings_empty_returns_unknown():
    result = analyze_recent_filings("AAPL", [])

    assert result["filing_risk_level"] == "unknown"
    assert result["warnings"]
