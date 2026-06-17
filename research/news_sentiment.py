from __future__ import annotations


POSITIVE_PATTERNS = {
    "raised guidance": ["raised guidance", "raises guidance", "raises outlook", "boosts outlook"],
    "record revenue/profit": ["record revenue", "record profit", "record earnings"],
    "buyback": ["buyback", "share repurchase"],
    "analyst upgrade": ["analyst upgrade", "upgraded by", "upgrade to buy"],
    "FDA approval": ["fda approval", "approved by fda"],
    "contract win": ["contract win", "contract award", "wins contract"],
    "acquisition premium": ["acquisition premium", "takeover premium", "buyout premium"],
    "debt reduction": ["debt reduction", "reduced debt", "deleveraging"],
}

NEGATIVE_PATTERNS = {
    "lowered guidance": ["lowered guidance", "cuts guidance", "cuts outlook", "reduced outlook"],
    "investigation": ["investigation", "investigating"],
    "SEC probe": ["sec probe", "sec investigation"],
    "DOJ probe": ["doj probe", "justice department probe", "department of justice"],
    "accounting issue": ["accounting issue", "accounting irregularity"],
    "restatement": ["restatement", "restate financials", "non-reliance"],
    "bankruptcy": ["bankruptcy", "chapter 11", "insolvency"],
    "CEO/CFO departure": ["ceo departure", "cfo departure", "chief executive officer resigned", "chief financial officer resigned"],
    "missed earnings": ["missed earnings", "earnings miss", "misses estimates"],
    "downgrade": ["downgrade", "downgraded by"],
    "lawsuit": ["lawsuit", "class action", "litigation"],
    "cybersecurity breach": ["cybersecurity breach", "data breach", "ransomware"],
    "dilution/offering": ["secondary offering", "stock offering", "dilution", "at-the-market offering"],
}

CRITICAL_FLAGS = {"bankruptcy", "restatement", "SEC probe", "DOJ probe", "accounting issue"}
HIGH_FLAGS = {"lowered guidance", "investigation", "CEO/CFO departure", "missed earnings", "lawsuit", "cybersecurity breach", "dilution/offering"}


def _article_text(article: dict) -> str:
    return " ".join(str(article.get(key, "") or "") for key in ("headline", "summary", "source")).lower()


def evaluate_news_sentiment(
    ticker: str,
    articles: list[dict],
    config: dict | None = None,
) -> dict:
    normalized = str(ticker or "").strip().upper()
    warnings: list[str] = []
    if not articles:
        return {
            "ok": True,
            "ticker": normalized,
            "sentiment_label": "unknown",
            "headline_risk_level": "unknown",
            "trade_impact": "unknown",
            "risk_multiplier": 1.0,
            "score_adjustment": 0.0,
            "risk_flags": [],
            "positive_flags": [],
            "warnings": ["No recent news articles were available."],
        }

    positive_flags: list[str] = []
    risk_flags: list[str] = []
    for article in articles:
        if not isinstance(article, dict):
            continue
        text = _article_text(article)
        for label, patterns in POSITIVE_PATTERNS.items():
            if any(pattern in text for pattern in patterns):
                positive_flags.append(label)
        for label, patterns in NEGATIVE_PATTERNS.items():
            if any(pattern in text for pattern in patterns):
                risk_flags.append(label)

    positive_flags = list(dict.fromkeys(positive_flags))
    risk_flags = list(dict.fromkeys(risk_flags))
    if any(flag in CRITICAL_FLAGS for flag in risk_flags):
        risk_level = "critical"
    elif any(flag in HIGH_FLAGS for flag in risk_flags) or len(risk_flags) >= 2:
        risk_level = "high"
    elif risk_flags:
        risk_level = "medium"
    else:
        risk_level = "low"

    if risk_level == "critical":
        sentiment = "negative"
        trade_impact = "blocking"
        risk_multiplier = 0.0
        score_adjustment = -30.0
    elif risk_level == "high":
        sentiment = "mixed" if positive_flags else "negative"
        trade_impact = "caution"
        risk_multiplier = 0.5
        score_adjustment = -10.0
    elif risk_level == "medium":
        sentiment = "mixed" if positive_flags else "negative"
        trade_impact = "caution"
        risk_multiplier = 0.8
        score_adjustment = -4.0
    elif positive_flags:
        sentiment = "positive"
        trade_impact = "supportive"
        risk_multiplier = 1.0
        score_adjustment = 3.0
    else:
        sentiment = "neutral"
        trade_impact = "neutral"
        risk_multiplier = 1.0
        score_adjustment = 0.0

    return {
        "ok": True,
        "ticker": normalized,
        "sentiment_label": sentiment,
        "headline_risk_level": risk_level,
        "trade_impact": trade_impact,
        "risk_multiplier": risk_multiplier,
        "score_adjustment": score_adjustment,
        "risk_flags": risk_flags,
        "positive_flags": positive_flags,
        "warnings": warnings,
    }
