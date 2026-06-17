from research.news_sentiment import evaluate_news_sentiment


def test_positive_headlines_are_supportive():
    result = evaluate_news_sentiment(
        "AAPL",
        [{"headline": "AAPL announces buyback after analyst upgrade and raised guidance", "summary": ""}],
    )

    assert result["sentiment_label"] == "positive"
    assert result["trade_impact"] == "supportive"
    assert result["score_adjustment"] > 0


def test_investigation_headline_is_high_risk():
    result = evaluate_news_sentiment(
        "AAPL",
        [{"headline": "AAPL faces investigation and lawsuit after missed earnings", "summary": ""}],
    )

    assert result["headline_risk_level"] == "high"
    assert result["trade_impact"] == "caution"
    assert "investigation" in result["risk_flags"]


def test_restatement_or_bankruptcy_headline_is_critical():
    result = evaluate_news_sentiment(
        "AAPL",
        [{"headline": "AAPL announces accounting issue and restatement", "summary": ""}],
    )

    assert result["headline_risk_level"] == "critical"
    assert result["trade_impact"] == "blocking"
    assert result["risk_multiplier"] == 0.0


def test_unknown_news_warns_without_crashing():
    result = evaluate_news_sentiment("AAPL", [])

    assert result["ok"] is True
    assert result["sentiment_label"] == "unknown"
    assert result["warnings"]
