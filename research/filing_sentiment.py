from __future__ import annotations


def evaluate_filing_sentiment(
    ticker: str,
    filing_analysis: dict,
    earnings_analysis: dict | None = None,
    config: dict | None = None,
) -> dict:
    analysis = filing_analysis if isinstance(filing_analysis, dict) else {}
    earnings = earnings_analysis if isinstance(earnings_analysis, dict) else {}
    risk_level = str(analysis.get("filing_risk_level", "unknown")).lower()
    earnings_label = str(earnings.get("sentiment_label", "")).lower()
    positive = list(analysis.get("positive_flags", []) or []) + list(earnings.get("positive_flags", []) or [])
    risks = list(analysis.get("risk_flags", []) or []) + list(earnings.get("risk_flags", []) or [])
    reasons: list[str] = []
    warnings: list[str] = []

    if risk_level == "critical":
        sentiment = "negative"
        trade_impact = "blocking"
        risk_multiplier = 0.0
        score_adjustment = -30.0
        reasons.append("Critical SEC filing risk blocks new paper recommendations.")
    elif risk_level == "high":
        sentiment = "negative" if earnings_label not in {"positive"} else "mixed"
        trade_impact = "caution"
        risk_multiplier = 0.5
        score_adjustment = -10.0
        reasons.append("High SEC filing risk reduces trade size and score.")
    elif risk_level == "medium":
        sentiment = "mixed" if positive else "negative"
        trade_impact = "caution"
        risk_multiplier = 0.75
        score_adjustment = -5.0
        reasons.append("Medium SEC filing risk warrants caution.")
    elif earnings_label == "positive" or (positive and not risks):
        sentiment = "positive"
        trade_impact = "supportive"
        risk_multiplier = 1.0
        score_adjustment = 3.0
        reasons.append("Filing context is supportive.")
    elif earnings_label == "negative" or risks:
        sentiment = "negative"
        trade_impact = "caution"
        risk_multiplier = 0.85
        score_adjustment = -4.0
        reasons.append("Filing context contains cautionary signals.")
    elif risk_level == "low":
        sentiment = "neutral"
        trade_impact = "neutral"
        risk_multiplier = 1.0
        score_adjustment = 0.0
        reasons.append("Recent filing risk is low.")
    else:
        sentiment = "unknown"
        trade_impact = "unknown"
        risk_multiplier = 1.0
        score_adjustment = 0.0
        warnings.append("SEC filing sentiment is unknown.")

    return {
        "ok": True,
        "ticker": str(ticker or "").upper(),
        "sentiment_label": sentiment,
        "filing_risk_level": risk_level if risk_level in {"low", "medium", "high", "critical"} else "unknown",
        "trade_impact": trade_impact,
        "risk_multiplier": risk_multiplier,
        "score_adjustment": score_adjustment,
        "reasons": reasons,
        "warnings": warnings,
    }

