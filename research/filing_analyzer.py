from __future__ import annotations

from typing import Any


EVENT_PATTERNS = {
    "earnings release": ["earnings release", "results of operations", "financial results", "item 2.02"],
    "guidance update": ["guidance", "outlook", "forecast", "raised guidance", "lowered guidance"],
    "CEO/CFO departure": ["chief executive officer resigned", "ceo resigned", "chief financial officer resigned", "cfo resigned", "departure"],
    "auditor change": ["change in registrant's certifying accountant", "dismissed auditor", "new independent registered public accounting firm", "item 4.01"],
    "restructuring": ["restructuring", "workforce reduction", "layoff", "cost reduction plan"],
    "debt/liquidity issue": ["liquidity", "debt covenant", "default", "credit facility", "going concern"],
    "acquisition/divestiture": ["acquisition", "merger", "divestiture", "asset sale"],
    "litigation/regulatory issue": ["litigation", "investigation", "regulatory", "subpoena", "consent order"],
    "going concern language": ["going concern"],
    "restatement/amendment": ["restatement", "non-reliance", "amendment", "amended"],
    "cybersecurity incident": ["cybersecurity incident", "data breach", "ransomware"],
    "bankruptcy/restructuring warning": ["bankruptcy", "chapter 11", "reorganization"],
}

POSITIVE_PATTERNS = {
    "share repurchase": ["share repurchase", "buyback"],
    "strategic transaction": ["strategic partnership", "major contract", "contract award"],
    "positive earnings": ["record revenue", "raised guidance", "beat expectations"],
}

CRITICAL_EVENTS = {"going concern language", "bankruptcy/restructuring warning", "restatement/amendment"}
HIGH_EVENTS = {"CEO/CFO departure", "auditor change", "debt/liquidity issue", "litigation/regulatory issue", "cybersecurity incident"}


def _text_for(filing: dict, filing_text: str | None = None) -> str:
    parts = [
        filing.get("form"),
        filing.get("description"),
        " ".join(filing.get("items", [])) if isinstance(filing.get("items"), list) else filing.get("items"),
        filing_text,
    ]
    return " ".join(str(part or "") for part in parts).lower()


def classify_filing_importance(filing: dict) -> dict:
    form = str((filing or {}).get("form", "OTHER")).upper()
    score = {"8-K": 80, "10-Q": 70, "10-K": 75, "S-1": 85}.get(form, 35)
    label = "high" if score >= 75 else "medium" if score >= 60 else "low"
    return {"ok": True, "form": form, "importance": label, "importance_score": score, "warnings": [], "errors": []}


def detect_material_event_flags(filing: dict, filing_text: str | None = None) -> dict:
    text = _text_for(filing, filing_text)
    material_events = []
    risk_flags = []
    positive_flags = []
    for label, keywords in EVENT_PATTERNS.items():
        if any(keyword in text for keyword in keywords):
            material_events.append(label)
            if label in CRITICAL_EVENTS or label in HIGH_EVENTS:
                risk_flags.append(label)
    for label, keywords in POSITIVE_PATTERNS.items():
        if any(keyword in text for keyword in keywords):
            positive_flags.append(label)
    return {
        "ok": True,
        "accession_number": filing.get("accession_number"),
        "form": filing.get("form"),
        "material_events": list(dict.fromkeys(material_events)),
        "risk_flags": list(dict.fromkeys(risk_flags)),
        "positive_flags": list(dict.fromkeys(positive_flags)),
        "warnings": [],
        "errors": [],
    }


def analyze_recent_filings(
    ticker: str,
    filings: list[dict],
    config: dict | None = None,
) -> dict:
    recent = []
    material_events: list[str] = []
    risk_flags: list[str] = []
    positive_flags: list[str] = []
    for filing in filings or []:
        if not isinstance(filing, dict):
            continue
        importance = classify_filing_importance(filing)
        event_flags = detect_material_event_flags(filing)
        enriched = {**filing, "importance": importance, "event_flags": event_flags}
        recent.append(enriched)
        material_events.extend(event_flags.get("material_events", []))
        risk_flags.extend(event_flags.get("risk_flags", []))
        positive_flags.extend(event_flags.get("positive_flags", []))

    unique_risks = list(dict.fromkeys(risk_flags))
    if any(item in CRITICAL_EVENTS for item in unique_risks):
        risk_level = "critical"
    elif any(item in HIGH_EVENTS for item in unique_risks) or len(unique_risks) >= 2:
        risk_level = "high"
    elif unique_risks:
        risk_level = "medium"
    elif recent:
        risk_level = "low"
    else:
        risk_level = "unknown"
    return {
        "ok": True,
        "ticker": str(ticker or "").upper(),
        "filing_risk_level": risk_level,
        "recent_filings": recent,
        "material_events": list(dict.fromkeys(material_events)),
        "risk_flags": unique_risks,
        "positive_flags": list(dict.fromkeys(positive_flags)),
        "warnings": [] if recent else ["No recent filings were available for deterministic analysis."],
        "errors": [],
    }

