from __future__ import annotations


POSITIVE_TERMS = ["beat", "record", "raised guidance", "improved margin", "cash flow", "strong demand", "exceeded"]
NEGATIVE_TERMS = ["miss", "lowered guidance", "decline", "impairment", "weak demand", "cost pressure", "headwind", "below expectations"]


def extract_earnings_release_sections(filing_text: str) -> dict:
    text = str(filing_text or "")
    lower = text.lower()
    earnings_detected = any(term in lower for term in ["earnings", "financial results", "results of operations", "revenue"])
    guidance_detected = "guidance" in lower or "outlook" in lower
    snippets = []
    for sentence in text.replace("\n", " ").split("."):
        lowered = sentence.lower()
        if any(term in lowered for term in POSITIVE_TERMS + NEGATIVE_TERMS + ["guidance", "revenue", "margin"]):
            snippets.append(sentence.strip()[:240])
    return {
        "ok": True,
        "earnings_detected": earnings_detected,
        "guidance_detected": guidance_detected,
        "key_sections": [snippet for snippet in snippets if snippet][:8],
        "warnings": [],
        "errors": [],
    }


def analyze_earnings_8k(
    ticker: str,
    filing: dict,
    filing_text: str,
    config: dict | None = None,
) -> dict:
    sections = extract_earnings_release_sections(filing_text)
    lower = str(filing_text or "").lower()
    positive_hits = [term for term in POSITIVE_TERMS if term in lower]
    negative_hits = [term for term in NEGATIVE_TERMS if term in lower]
    earnings_detected = bool(sections.get("earnings_detected")) or str(filing.get("form", "")).upper() == "8-K" and "2.02" in " ".join(filing.get("items", []))
    if positive_hits and negative_hits:
        label = "mixed"
    elif positive_hits:
        label = "positive"
    elif negative_hits:
        label = "negative"
    elif earnings_detected:
        label = "neutral"
    else:
        label = "unknown"
    confidence = min(1.0, 0.25 + 0.15 * (len(positive_hits) + len(negative_hits)) + (0.2 if earnings_detected else 0.0))
    return {
        "ok": bool(filing_text),
        "ticker": str(ticker or "").upper(),
        "filing_date": filing.get("filing_date"),
        "earnings_detected": earnings_detected,
        "guidance_detected": bool(sections.get("guidance_detected")),
        "sentiment_label": label,
        "confidence": round(confidence if filing_text else 0.0, 2),
        "key_points": sections.get("key_sections", []),
        "risk_flags": negative_hits,
        "positive_flags": positive_hits,
        "warnings": [] if filing_text else ["Filing text is unavailable."],
        "errors": [] if filing_text else ["Filing text is required for earnings 8-K analysis."],
    }

