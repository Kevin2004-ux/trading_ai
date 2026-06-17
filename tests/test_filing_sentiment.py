from research.filing_sentiment import evaluate_filing_sentiment


def test_positive_filing_context_adds_small_score_boost():
    result = evaluate_filing_sentiment(
        "AAPL",
        {"filing_risk_level": "low", "positive_flags": ["share repurchase"], "risk_flags": []},
        {"sentiment_label": "positive", "positive_flags": ["raised guidance"], "risk_flags": []},
    )

    assert result["sentiment_label"] == "positive"
    assert result["trade_impact"] == "supportive"
    assert result["score_adjustment"] > 0


def test_high_risk_reduces_multiplier():
    result = evaluate_filing_sentiment(
        "AAPL",
        {"filing_risk_level": "high", "positive_flags": [], "risk_flags": ["auditor change"]},
    )

    assert result["trade_impact"] == "caution"
    assert result["risk_multiplier"] == 0.5
    assert result["score_adjustment"] < 0


def test_critical_risk_blocks_new_paper_trades():
    result = evaluate_filing_sentiment(
        "AAPL",
        {"filing_risk_level": "critical", "positive_flags": [], "risk_flags": ["going concern language"]},
    )

    assert result["trade_impact"] == "blocking"
    assert result["risk_multiplier"] == 0.0
    assert result["score_adjustment"] <= -30


def test_unknown_allows_with_warning():
    result = evaluate_filing_sentiment("AAPL", {"filing_risk_level": "unknown"})

    assert result["trade_impact"] == "unknown"
    assert result["risk_multiplier"] == 1.0
    assert result["warnings"]
