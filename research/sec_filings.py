from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

import pandas as pd
import requests

import config


SOURCE_FMP = "fmp"
SOURCE_MOCK = "mock"
SOURCE_SEC = "sec"
SOURCE_UNAVAILABLE = "unavailable"
FMP_BASE_URL = "https://financialmodelingprep.com"

CANONICAL_FILING_TYPES = {"10-K", "10-Q", "8-K", "S-3", "424B5"}
DEFAULT_FILING_TYPES = ["10-K", "10-Q", "8-K", "S-3", "424B5"]

NEGATIVE_FILING_PATTERNS = {
    "dilution_offering": {
        "keywords": ["offering", "dilution", "shelf registration", "atm program", "at-the-market", "424b5", "s-3"],
        "signal": "Potential dilution or offering activity.",
        "score": 56.0,
    },
    "going_concern": {
        "keywords": ["going concern"],
        "signal": "Going concern language appeared in filings.",
        "score": 40.0,
    },
    "debt_covenant": {
        "keywords": ["debt covenant", "covenant breach", "credit agreement amendment", "liquidity covenant"],
        "signal": "Debt covenant or financing pressure was disclosed.",
        "score": 28.0,
    },
    "material_weakness": {
        "keywords": ["material weakness", "internal control deficiency", "ineffective internal control"],
        "signal": "Material weakness or control deficiency was disclosed.",
        "score": 30.0,
    },
    "litigation_investigation": {
        "keywords": ["litigation", "lawsuit", "investigation", "sec inquiry", "doj", "subpoena", "probe"],
        "signal": "Litigation or investigation risk was disclosed.",
        "score": 24.0,
    },
    "restatement": {
        "keywords": ["restatement", "restate", "non-reliance"],
        "signal": "Restatement or non-reliance language was disclosed.",
        "score": 36.0,
    },
    "guidance_withdrawal": {
        "keywords": ["withdraw guidance", "guidance withdrawn", "suspend outlook"],
        "signal": "Guidance withdrawal was disclosed.",
        "score": 26.0,
    },
    "management_departure": {
        "keywords": ["chief executive officer resigned", "chief financial officer resigned", "management departure", "resigned as ceo", "resigned as cfo"],
        "signal": "Management departure was disclosed.",
        "score": 20.0,
    },
    "bankruptcy_restructuring": {
        "keywords": ["bankruptcy", "chapter 11", "restructuring", "reorganization"],
        "signal": "Bankruptcy or restructuring risk was disclosed.",
        "score": 42.0,
    },
    "customer_loss": {
        "keywords": ["customer loss", "lost customer", "termination by customer", "major customer"],
        "signal": "A significant customer concentration risk or loss was disclosed.",
        "score": 18.0,
    },
    "cybersecurity_incident": {
        "keywords": ["cybersecurity incident", "data breach", "security incident", "ransomware"],
        "signal": "Cybersecurity incident risk was disclosed.",
        "score": 22.0,
    },
    "regulatory_risk": {
        "keywords": ["regulatory", "compliance issue", "warning letter", "consent order"],
        "signal": "Regulatory risk was disclosed.",
        "score": 18.0,
    },
}

POSITIVE_FILING_PATTERNS = {
    "buyback": {
        "keywords": ["share repurchase", "buyback", "repurchase program"],
        "signal": "Share repurchase activity was disclosed.",
        "score_offset": 10.0,
    },
    "strategic_partnership": {
        "keywords": ["strategic partnership", "collaboration agreement", "joint venture"],
        "signal": "Strategic partnership or collaboration was disclosed.",
        "score_offset": 8.0,
    },
    "strong_contract": {
        "keywords": ["contract award", "multi-year agreement", "major contract", "backlog"],
        "signal": "Strong contract or backlog disclosure was present.",
        "score_offset": 7.0,
    },
    "merger_acquisition": {
        "keywords": ["acquisition", "merger agreement", "asset purchase agreement"],
        "signal": "A merger or acquisition event was disclosed.",
        "score_offset": 2.0,
    },
}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _get_fmp_api_key() -> str | None:
    return getattr(config, "FMP_API_KEY", None)


def _response(
    ok: bool,
    ticker: str,
    *,
    source: str,
    data: dict | None = None,
    error: str | None = None,
) -> dict:
    return {
        "ok": ok,
        "ticker": str(ticker or "").strip().upper(),
        "source": source,
        "timestamp": _now_iso(),
        "data": data,
        "error": error,
    }


def _normalize_timestamp(value: Any) -> str | None:
    if value in (None, ""):
        return None
    try:
        ts = pd.Timestamp(value)
    except Exception:
        return None
    if ts.tzinfo is None:
        ts = ts.tz_localize("UTC")
    else:
        ts = ts.tz_convert("UTC")
    return ts.isoformat()


def _extract_list(payload: Any) -> list[dict]:
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if isinstance(payload, dict):
        for key in ("data", "results", "filings"):
            value = payload.get(key)
            if isinstance(value, list):
                return [item for item in value if isinstance(item, dict)]
    return []


def _normalize_filing_type(value: Any) -> str:
    raw = str(value or "").strip().upper()
    if raw in CANONICAL_FILING_TYPES:
        return raw
    if raw == "424B5":
        return "424B5"
    return "other"


def _combined_filing_text(raw_filing: dict) -> str:
    parts = [
        raw_filing.get("title"),
        raw_filing.get("description"),
        raw_filing.get("summary"),
        raw_filing.get("text"),
        raw_filing.get("item"),
        raw_filing.get("itemName"),
    ]
    return " ".join(str(part or "") for part in parts).lower()


def _keyword_matches(text: str, pattern_map: dict[str, dict[str, Any]]) -> tuple[list[str], list[str]]:
    matched_categories: list[str] = []
    matched_signals: list[str] = []
    for category, payload in pattern_map.items():
        keywords = payload.get("keywords", [])
        if any(keyword in text for keyword in keywords):
            matched_categories.append(category)
            matched_signals.append(str(payload.get("signal", category)))
    return matched_categories, matched_signals


def normalize_filing_item(
    raw_filing: dict,
) -> dict:
    ticker = str(raw_filing.get("symbol") or raw_filing.get("ticker") or "").strip().upper()
    filing_type = _normalize_filing_type(
        raw_filing.get("formType")
        or raw_filing.get("type")
        or raw_filing.get("filingType")
        or raw_filing.get("form")
    )
    filed_at = _normalize_timestamp(
        raw_filing.get("fillingDate")
        or raw_filing.get("filingDate")
        or raw_filing.get("acceptedDate")
        or raw_filing.get("date")
    )
    period = (
        raw_filing.get("periodOfReport")
        or raw_filing.get("period")
        or raw_filing.get("fiscalPeriod")
        or raw_filing.get("fiscalDate")
    )
    title = str(
        raw_filing.get("title")
        or raw_filing.get("description")
        or raw_filing.get("itemName")
        or f"{filing_type} filing"
    ).strip()
    summary = str(
        raw_filing.get("summary")
        or raw_filing.get("description")
        or raw_filing.get("text")
        or raw_filing.get("item")
        or ""
    ).strip()
    url = str(raw_filing.get("finalLink") or raw_filing.get("link") or raw_filing.get("url") or "").strip() or None
    source = str(raw_filing.get("source") or SOURCE_FMP).strip().lower() or SOURCE_FMP

    text = _combined_filing_text(raw_filing)
    risk_keywords, _ = _keyword_matches(text, NEGATIVE_FILING_PATTERNS)
    event_keywords, _ = _keyword_matches(text, POSITIVE_FILING_PATTERNS)

    return {
        "ticker": ticker,
        "filing_type": filing_type,
        "filed_at": filed_at,
        "period": period,
        "title": title,
        "url": url,
        "summary": summary,
        "risk_keywords": risk_keywords,
        "event_keywords": event_keywords,
        "source": source if source in {SOURCE_FMP, SOURCE_MOCK, SOURCE_SEC, SOURCE_UNAVAILABLE} else SOURCE_FMP,
    }


def score_filing_risk(
    filing_analysis: dict,
) -> dict:
    filings_analyzed = int(filing_analysis.get("filings_analyzed", 0) or 0)
    ticker = str(filing_analysis.get("ticker") or "").upper()
    if filings_analyzed <= 0:
        return {
            "ok": False,
            "ticker": ticker,
            "filings_analyzed": 0,
            "filing_risk_label": "unavailable",
            "filing_risk_score": 0.0,
            "positive_filing_signals": [],
            "negative_filing_signals": [],
            "risk_flags": [],
            "recent_material_events": [],
            "summary": "SEC filing context is unavailable.",
            "sources": filing_analysis.get("sources", []),
            "error": filing_analysis.get("error") or "No SEC filings were available for analysis.",
        }

    score = 18.0
    negative_categories = filing_analysis.get("negative_categories", {})
    positive_categories = filing_analysis.get("positive_categories", {})
    for payload in negative_categories.values():
        score += float(payload.get("score", 0.0))
    for payload in positive_categories.values():
        score -= float(payload.get("score_offset", 0.0))

    negative_signals = filing_analysis.get("negative_filing_signals", [])
    positive_signals = filing_analysis.get("positive_filing_signals", [])
    risk_flags = filing_analysis.get("risk_flags", [])
    recent_material_events = filing_analysis.get("recent_material_events", [])

    score = max(0.0, min(100.0, round(score, 2)))
    if score >= 70:
        label = "high"
    elif score >= 40:
        label = "medium"
    else:
        label = "low"

    summary_parts = []
    if negative_signals:
        summary_parts.append(f"Negative filing signal: {negative_signals[0]}")
    if positive_signals:
        summary_parts.append(f"Positive filing signal: {positive_signals[0]}")
    if risk_flags:
        summary_parts.append(f"Risk flag: {risk_flags[0]}")
    summary = " ".join(summary_parts) if summary_parts else "Recent SEC filings do not show major deterministic risk flags."

    return {
        "ok": True,
        "ticker": ticker,
        "filings_analyzed": filings_analyzed,
        "filing_risk_label": label,
        "filing_risk_score": score,
        "positive_filing_signals": positive_signals,
        "negative_filing_signals": negative_signals,
        "risk_flags": risk_flags,
        "recent_material_events": recent_material_events,
        "summary": summary,
        "sources": filing_analysis.get("sources", []),
        "error": None,
    }


def analyze_filing_risks(
    filings: list[dict]
) -> dict:
    normalized_filings = [normalize_filing_item(item) for item in filings if isinstance(item, dict)]
    ticker = str(normalized_filings[0].get("ticker") if normalized_filings else "").upper()
    if not normalized_filings:
        return score_filing_risk(
            {
                "ticker": ticker,
                "filings_analyzed": 0,
                "sources": [],
                "error": "No SEC filings were available for analysis.",
            }
        )

    negative_categories: dict[str, dict[str, Any]] = {}
    positive_categories: dict[str, dict[str, Any]] = {}
    negative_filing_signals: list[str] = []
    positive_filing_signals: list[str] = []
    risk_flags: list[str] = []
    recent_material_events: list[str] = []
    sources: list[str] = []

    for filing in normalized_filings:
        filing_source = filing.get("source")
        if filing_source:
            sources.append(str(filing_source))
        text = f"{filing.get('title', '')} {filing.get('summary', '')}".lower()
        matched_negative, negative_signals = _keyword_matches(text, NEGATIVE_FILING_PATTERNS)
        matched_positive, positive_signals = _keyword_matches(text, POSITIVE_FILING_PATTERNS)

        for category in matched_negative:
            negative_categories.setdefault(category, NEGATIVE_FILING_PATTERNS[category])
        for category in matched_positive:
            positive_categories.setdefault(category, POSITIVE_FILING_PATTERNS[category])
        negative_filing_signals.extend(negative_signals)
        positive_filing_signals.extend(positive_signals)

        filing_type = str(filing.get("filing_type", "other")).upper()
        title = str(filing.get("title") or filing_type)
        if matched_negative or matched_positive:
            recent_material_events.append(f"{filing_type}: {title}")

    if "dilution_offering" in negative_categories:
        risk_flags.append("Recent filing language suggests dilution or offering risk.")
    if "material_weakness" in negative_categories:
        risk_flags.append("Material weakness or internal-control risk was disclosed.")
    if "litigation_investigation" in negative_categories:
        risk_flags.append("Litigation or investigation exposure was disclosed.")
    if "bankruptcy_restructuring" in negative_categories:
        risk_flags.append("Restructuring or solvency risk was disclosed.")

    return score_filing_risk(
        {
            "ticker": ticker,
            "filings_analyzed": len(normalized_filings),
            "negative_categories": negative_categories,
            "positive_categories": positive_categories,
            "positive_filing_signals": list(dict.fromkeys(positive_filing_signals)),
            "negative_filing_signals": list(dict.fromkeys(negative_filing_signals)),
            "risk_flags": list(dict.fromkeys(risk_flags)),
            "recent_material_events": list(dict.fromkeys(recent_material_events))[:8],
            "sources": list(dict.fromkeys(sources)),
        }
    )


def summarize_filing_context(
    ticker: str,
    filings: list[dict],
    filing_analysis: dict
) -> dict:
    ticker = str(ticker or "").strip().upper()
    latest_filing = filings[0] if filings else {}
    return {
        "ticker": ticker,
        "filing_risk_label": filing_analysis.get("filing_risk_label", "unavailable"),
        "filing_risk_score": filing_analysis.get("filing_risk_score", 0.0),
        "latest_filing_type": latest_filing.get("filing_type"),
        "latest_filed_at": latest_filing.get("filed_at"),
        "recent_material_events": filing_analysis.get("recent_material_events", []),
        "summary": filing_analysis.get("summary", "SEC filing context is unavailable."),
    }


def _fetch_fmp_filings(
    ticker: str,
    lookback_days: int,
    api_key: str,
) -> list[dict]:
    cutoff = (datetime.now(timezone.utc) - timedelta(days=lookback_days)).strftime("%Y-%m-%d")
    candidate_urls = [
        f"{FMP_BASE_URL}/stable/sec-filings-search/symbol?symbol={ticker}&from={cutoff}&apikey={api_key}",
        f"{FMP_BASE_URL}/api/v3/sec_filings/{ticker}?apikey={api_key}",
    ]

    last_error: str | None = None
    for url in candidate_urls:
        try:
            response = requests.get(url, timeout=20)
            response.raise_for_status()
            payload = response.json()
            rows = _extract_list(payload)
            if rows:
                return rows
            last_error = "Provider returned no filing rows."
        except requests.exceptions.RequestException as exc:
            last_error = str(exc)
    if last_error:
        raise requests.exceptions.RequestException(last_error)
    return []


def get_sec_filing_snapshot(
    ticker: str,
    filing_types: list[str] | None = None,
    lookback_days: int = 120
) -> dict:
    normalized_ticker = str(ticker or "").strip().upper()
    requested_types = [_normalize_filing_type(item) for item in (filing_types or DEFAULT_FILING_TYPES)]
    requested_types = [item for item in requested_types if item]

    api_key = _get_fmp_api_key()
    if not api_key:
        return _response(
            False,
            normalized_ticker,
            source=SOURCE_UNAVAILABLE,
            data={
                "filings": [],
                "filing_analysis": {
                    "ok": False,
                    "ticker": normalized_ticker,
                    "filings_analyzed": 0,
                    "filing_risk_label": "unavailable",
                    "filing_risk_score": 0.0,
                    "positive_filing_signals": [],
                    "negative_filing_signals": [],
                    "risk_flags": [],
                    "recent_material_events": [],
                    "summary": "SEC filing context is unavailable.",
                    "sources": [],
                    "error": "FMP_API_KEY is not configured.",
                },
                "filing_summary": {"ticker": normalized_ticker, "summary": "SEC filing context is unavailable."},
            },
            error="FMP_API_KEY is not configured.",
        )

    try:
        raw_rows = _fetch_fmp_filings(normalized_ticker, lookback_days=lookback_days, api_key=api_key)
        normalized = [normalize_filing_item(row) for row in raw_rows]
        if requested_types:
            normalized = [row for row in normalized if row.get("filing_type") in requested_types]
        normalized = sorted(
            normalized,
            key=lambda row: row.get("filed_at") or "",
            reverse=True,
        )
        if not normalized:
            return _response(
                False,
                normalized_ticker,
                source=SOURCE_FMP,
                data={
                    "filings": [],
                    "filing_analysis": analyze_filing_risks([]),
                    "filing_summary": {"ticker": normalized_ticker, "summary": "No recent filings matched the requested filters."},
                },
                error="No recent filings matched the requested filters.",
            )

        analysis = analyze_filing_risks(normalized)
        summary = summarize_filing_context(normalized_ticker, normalized, analysis)
        return _response(
            True,
            normalized_ticker,
            source=SOURCE_FMP,
            data={
                "filings": normalized,
                "filing_analysis": analysis,
                "filing_summary": summary,
            },
        )
    except requests.exceptions.RequestException as exc:
        return _response(
            False,
            normalized_ticker,
            source=SOURCE_FMP,
            data={
                "filings": [],
                "filing_analysis": analyze_filing_risks([]),
                "filing_summary": {"ticker": normalized_ticker, "summary": "SEC filing context is unavailable."},
            },
            error=f"Failed to fetch SEC filings: {exc}",
        )
    except Exception as exc:
        return _response(
            False,
            normalized_ticker,
            source=SOURCE_FMP,
            data={
                "filings": [],
                "filing_analysis": analyze_filing_risks([]),
                "filing_summary": {"ticker": normalized_ticker, "summary": "SEC filing context is unavailable."},
            },
            error=f"Unexpected error while fetching SEC filings: {exc}",
        )
