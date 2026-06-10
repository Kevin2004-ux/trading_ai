from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import pandas as pd
import requests

import config


SOURCE_FMP = "fmp"
SOURCE_MOCK = "mock"
SOURCE_UNAVAILABLE = "unavailable"
FMP_BASE_URL = "https://financialmodelingprep.com"

POSITIVE_TRANSCRIPT_PATTERNS = {
    "raised_guidance": {"keywords": ["raise guidance", "raised guidance", "increased outlook", "upwardly revised"], "signal": "Management discussed raised guidance.", "score": 16.0},
    "strong_demand": {"keywords": ["strong demand", "healthy demand", "robust demand"], "signal": "Management cited strong demand.", "score": 10.0},
    "margin_expansion": {"keywords": ["margin expansion", "gross margin expansion", "operating margin expansion"], "signal": "Margin expansion was discussed.", "score": 10.0},
    "revenue_acceleration": {"keywords": ["revenue acceleration", "accelerating revenue", "growth accelerated"], "signal": "Revenue acceleration was discussed.", "score": 10.0},
    "backlog_strength": {"keywords": ["backlog strength", "record backlog", "strong backlog"], "signal": "Backlog strength was discussed.", "score": 8.0},
    "pricing_power": {"keywords": ["pricing power", "price increases held", "pricing remains strong"], "signal": "Pricing power was discussed.", "score": 8.0},
    "customer_growth": {"keywords": ["customer growth", "customer additions", "new customers"], "signal": "Customer growth was discussed.", "score": 7.0},
    "ai_cloud_strength": {"keywords": ["ai demand", "cloud strength", "ai workload", "product strength"], "signal": "AI, cloud, or product strength was discussed.", "score": 6.0},
    "cost_discipline": {"keywords": ["cost discipline", "expense discipline", "efficiency"], "signal": "Cost discipline was discussed.", "score": 6.0},
}

NEGATIVE_TRANSCRIPT_PATTERNS = {
    "lowered_guidance": {"keywords": ["lower guidance", "lowered guidance", "reduced outlook", "cut guidance"], "signal": "Management discussed lowered guidance.", "score": 18.0},
    "margin_pressure": {"keywords": ["margin pressure", "gross margin pressure", "compressed margins"], "signal": "Margin pressure was discussed.", "score": 12.0},
    "weak_demand": {"keywords": ["weak demand", "soft demand", "demand remains muted"], "signal": "Weak demand was discussed.", "score": 12.0},
    "inventory_build": {"keywords": ["inventory build", "inventory elevated", "inventory overhang"], "signal": "Inventory build was discussed.", "score": 8.0},
    "churn": {"keywords": ["churn", "customer loss", "attrition"], "signal": "Churn or attrition was discussed.", "score": 8.0},
    "pricing_pressure": {"keywords": ["pricing pressure", "price competition", "discounting"], "signal": "Pricing pressure was discussed.", "score": 10.0},
    "macro_headwinds": {"keywords": ["macro headwinds", "macroeconomic uncertainty", "macro pressure"], "signal": "Macro headwinds were discussed.", "score": 8.0},
    "delayed_deals": {"keywords": ["delayed deals", "longer sales cycles", "deal slippage"], "signal": "Delayed deals or elongated sales cycles were discussed.", "score": 6.0},
    "regulatory_issues": {"keywords": ["regulatory issue", "regulatory headwind", "compliance pressure"], "signal": "Regulatory issues were discussed.", "score": 8.0},
    "cash_burn": {"keywords": ["cash burn", "negative free cash flow", "use of cash"], "signal": "Cash burn was discussed.", "score": 8.0},
    "cautious_tone": {"keywords": ["remain cautious", "remains cautious", "cautious on demand", "visibility remains limited"], "signal": "Management tone was cautious.", "score": 4.0},
}

RAISED_GUIDANCE_KEYWORDS = ["raise guidance", "raised guidance", "increased outlook", "upwardly revised"]
LOWERED_GUIDANCE_KEYWORDS = ["lower guidance", "lowered guidance", "reduced outlook", "cut guidance", "withdraw guidance"]
MAINTAINED_GUIDANCE_KEYWORDS = ["maintain guidance", "maintained guidance", "reaffirm guidance", "reaffirmed outlook"]


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


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


def _get_fmp_api_key() -> str | None:
    return getattr(config, "FMP_API_KEY", None)


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
        for key in ("data", "results", "transcripts"):
            value = payload.get(key)
            if isinstance(value, list):
                return [item for item in value if isinstance(item, dict)]
    return []


def _combined_transcript_text(raw_transcript: dict) -> str:
    parts = [
        raw_transcript.get("title"),
        raw_transcript.get("content"),
        raw_transcript.get("transcript"),
        raw_transcript.get("preparedRemarks"),
        raw_transcript.get("qa"),
        raw_transcript.get("summary"),
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


def normalize_transcript_item(
    raw_transcript: dict
) -> dict:
    ticker = str(raw_transcript.get("symbol") or raw_transcript.get("ticker") or "").strip().upper()
    year = raw_transcript.get("year") or raw_transcript.get("fiscalYear")
    quarter = raw_transcript.get("quarter") or raw_transcript.get("fiscalQuarter")
    reported_at = _normalize_timestamp(
        raw_transcript.get("date")
        or raw_transcript.get("reportedDate")
        or raw_transcript.get("acceptedDate")
    )
    title = str(
        raw_transcript.get("title")
        or raw_transcript.get("headline")
        or f"{ticker} earnings transcript"
    ).strip()
    content = str(
        raw_transcript.get("content")
        or raw_transcript.get("transcript")
        or raw_transcript.get("preparedRemarks")
        or raw_transcript.get("summary")
        or ""
    ).strip()
    source = str(raw_transcript.get("source") or SOURCE_FMP).strip().lower() or SOURCE_FMP
    text = _combined_transcript_text(raw_transcript)
    positive_keywords, positive_signals = _keyword_matches(text, POSITIVE_TRANSCRIPT_PATTERNS)
    negative_keywords, negative_signals = _keyword_matches(text, NEGATIVE_TRANSCRIPT_PATTERNS)

    return {
        "ticker": ticker,
        "year": year,
        "quarter": quarter,
        "reported_at": reported_at,
        "title": title,
        "content": content,
        "positive_keywords": positive_keywords,
        "negative_keywords": negative_keywords,
        "positive_signals": positive_signals,
        "negative_signals": negative_signals,
        "source": source if source in {SOURCE_FMP, SOURCE_MOCK, SOURCE_UNAVAILABLE} else SOURCE_FMP,
    }


def analyze_transcript_sentiment(
    transcripts: list[dict]
) -> dict:
    normalized = [normalize_transcript_item(item) for item in transcripts if isinstance(item, dict)]
    ticker = str(normalized[0].get("ticker") if normalized else "").upper()
    if not normalized:
        return {
            "ok": False,
            "ticker": ticker,
            "quarters_analyzed": 0,
            "management_tone": "unknown",
            "positive_signals": [],
            "negative_signals": [],
            "risk_flags": [],
            "sources": [],
            "error": "No earnings transcripts were available for sentiment analysis.",
        }

    positive_categories: dict[str, dict[str, Any]] = {}
    negative_categories: dict[str, dict[str, Any]] = {}
    positive_signals: list[str] = []
    negative_signals: list[str] = []
    sources: list[str] = []
    score = 50.0

    for transcript in normalized:
        sources.append(str(transcript.get("source", SOURCE_FMP)))
        text = _combined_transcript_text(transcript)
        matched_positive, positive_items = _keyword_matches(text, POSITIVE_TRANSCRIPT_PATTERNS)
        matched_negative, negative_items = _keyword_matches(text, NEGATIVE_TRANSCRIPT_PATTERNS)
        for category in matched_positive:
            positive_categories.setdefault(category, POSITIVE_TRANSCRIPT_PATTERNS[category])
            score += float(POSITIVE_TRANSCRIPT_PATTERNS[category]["score"])
        for category in matched_negative:
            negative_categories.setdefault(category, NEGATIVE_TRANSCRIPT_PATTERNS[category])
            score -= float(NEGATIVE_TRANSCRIPT_PATTERNS[category]["score"])
        positive_signals.extend(positive_items)
        negative_signals.extend(negative_items)

    score = max(0.0, min(100.0, round(score, 2)))
    if score >= 65:
        tone = "positive"
    elif score <= 35:
        tone = "negative"
    elif negative_categories:
        tone = "cautious"
    else:
        tone = "neutral"

    risk_flags = []
    if "lowered_guidance" in negative_categories:
        risk_flags.append("Management discussed lowered guidance.")
    if "margin_pressure" in negative_categories:
        risk_flags.append("Margin pressure was discussed.")
    if "cash_burn" in negative_categories:
        risk_flags.append("Cash burn or negative cash flow was discussed.")

    return {
        "ok": True,
        "ticker": ticker,
        "quarters_analyzed": len(normalized),
        "management_tone": tone,
        "positive_signals": list(dict.fromkeys(positive_signals)),
        "negative_signals": list(dict.fromkeys(negative_signals)),
        "risk_flags": list(dict.fromkeys(risk_flags)),
        "sources": list(dict.fromkeys(sources)),
        "base_score": score,
        "positive_categories": positive_categories,
        "negative_categories": negative_categories,
        "error": None,
    }


def analyze_guidance_context(
    transcripts: list[dict]
) -> dict:
    normalized = [normalize_transcript_item(item) for item in transcripts if isinstance(item, dict)]
    ticker = str(normalized[0].get("ticker") if normalized else "").upper()
    if not normalized:
        return {
            "ok": False,
            "ticker": ticker,
            "guidance_label": "unavailable",
            "guidance_signals": [],
            "risk_flags": [],
            "error": "No earnings transcripts were available for guidance analysis.",
        }

    guidance_signals: list[str] = []
    risk_flags: list[str] = []
    guidance_label = "unclear"

    for transcript in normalized:
        text = _combined_transcript_text(transcript)
        if any(keyword in text for keyword in LOWERED_GUIDANCE_KEYWORDS):
            guidance_label = "lowered"
            guidance_signals.append("Management lowered or withdrew guidance.")
            risk_flags.append("Guidance tone is negative.")
            break
        if any(keyword in text for keyword in RAISED_GUIDANCE_KEYWORDS):
            guidance_label = "raised"
            guidance_signals.append("Management raised guidance.")
        elif any(keyword in text for keyword in MAINTAINED_GUIDANCE_KEYWORDS):
            if guidance_label != "raised":
                guidance_label = "maintained"
            guidance_signals.append("Management maintained or reaffirmed guidance.")

    return {
        "ok": True,
        "ticker": ticker,
        "guidance_label": guidance_label,
        "guidance_signals": list(dict.fromkeys(guidance_signals)),
        "risk_flags": list(dict.fromkeys(risk_flags)),
        "error": None,
    }


def score_earnings_quality(
    transcript_analysis: dict,
    guidance_context: dict
) -> dict:
    ticker = str(transcript_analysis.get("ticker") or guidance_context.get("ticker") or "").upper()
    if not transcript_analysis.get("ok"):
        return {
            "ok": False,
            "ticker": ticker,
            "source": SOURCE_UNAVAILABLE,
            "timestamp": _now_iso(),
            "quarters_analyzed": 0,
            "earnings_quality_label": "unavailable",
            "earnings_quality_score": 0.0,
            "management_tone": "unknown",
            "guidance_label": str(guidance_context.get("guidance_label", "unavailable")),
            "positive_signals": [],
            "negative_signals": [],
            "risk_flags": [],
            "summary": "Earnings transcript context is unavailable.",
            "sources": transcript_analysis.get("sources", []),
            "error": transcript_analysis.get("error") or guidance_context.get("error") or "No earnings transcripts were available.",
        }

    score = float(transcript_analysis.get("base_score", 50.0))
    guidance_label = str(guidance_context.get("guidance_label", "unclear")).lower()
    if guidance_label == "raised":
        score += 12.0
    elif guidance_label == "maintained":
        score += 4.0
    elif guidance_label == "lowered":
        score -= 16.0

    score = max(0.0, min(100.0, round(score, 2)))
    if score >= 68:
        label = "strong"
    elif score <= 35:
        label = "weak"
    else:
        label = "mixed"

    positive_signals = list(dict.fromkeys(transcript_analysis.get("positive_signals", [])))
    if guidance_label in {"raised", "maintained"}:
        positive_signals = list(dict.fromkeys(positive_signals + guidance_context.get("guidance_signals", [])))

    negative_signals = list(dict.fromkeys(transcript_analysis.get("negative_signals", [])))
    if guidance_label == "lowered":
        negative_signals = list(dict.fromkeys(negative_signals + guidance_context.get("guidance_signals", [])))

    risk_flags = list(dict.fromkeys(transcript_analysis.get("risk_flags", []) + guidance_context.get("risk_flags", [])))
    summary_parts = []
    if positive_signals:
        summary_parts.append(f"Positive: {positive_signals[0]}")
    if negative_signals:
        summary_parts.append(f"Negative: {negative_signals[0]}")
    if risk_flags:
        summary_parts.append(f"Risk: {risk_flags[0]}")

    return {
        "ok": True,
        "ticker": ticker,
        "source": SOURCE_FMP,
        "timestamp": _now_iso(),
        "quarters_analyzed": int(transcript_analysis.get("quarters_analyzed", 0) or 0),
        "earnings_quality_label": label,
        "earnings_quality_score": score,
        "management_tone": transcript_analysis.get("management_tone", "unknown"),
        "guidance_label": guidance_label if guidance_label in {"raised", "maintained", "lowered", "unclear"} else "unclear",
        "positive_signals": positive_signals,
        "negative_signals": negative_signals,
        "risk_flags": risk_flags,
        "summary": " ".join(summary_parts) if summary_parts else "Earnings transcript context is neutral.",
        "sources": transcript_analysis.get("sources", []),
        "error": None,
    }


def summarize_earnings_context(
    ticker: str,
    transcripts: list[dict],
    transcript_analysis: dict,
    guidance_context: dict
) -> dict:
    quality = score_earnings_quality(transcript_analysis, guidance_context)
    return {
        "ticker": str(ticker or "").strip().upper(),
        "quarters_analyzed": len(transcripts),
        "earnings_quality_label": quality.get("earnings_quality_label", "unavailable"),
        "earnings_quality_score": quality.get("earnings_quality_score", 0.0),
        "management_tone": quality.get("management_tone", "unknown"),
        "guidance_label": quality.get("guidance_label", "unavailable"),
        "summary": quality.get("summary", "Earnings transcript context is unavailable."),
    }


def _fetch_fmp_transcript_dates(
    ticker: str,
    api_key: str,
) -> list[dict]:
    candidate_urls = [
        f"{FMP_BASE_URL}/stable/earning-call-transcript-dates?symbol={ticker}&apikey={api_key}",
        f"{FMP_BASE_URL}/api/v4/earning_call_transcript?symbol={ticker}&apikey={api_key}",
    ]
    last_error: str | None = None
    for url in candidate_urls:
        try:
            response = requests.get(url, timeout=20)
            response.raise_for_status()
            rows = _extract_list(response.json())
            if rows:
                return rows
            last_error = "Provider returned no transcript dates."
        except requests.exceptions.RequestException as exc:
            last_error = str(exc)
    if last_error:
        raise requests.exceptions.RequestException(last_error)
    return []


def _fetch_fmp_transcript(
    ticker: str,
    year: Any,
    quarter: Any,
    api_key: str,
) -> list[dict]:
    candidate_urls = [
        f"{FMP_BASE_URL}/stable/earning-call-transcript?symbol={ticker}&year={year}&quarter={quarter}&apikey={api_key}",
        f"{FMP_BASE_URL}/api/v3/earning_call_transcript/{ticker}?quarter={quarter}&year={year}&apikey={api_key}",
    ]
    last_error: str | None = None
    for url in candidate_urls:
        try:
            response = requests.get(url, timeout=20)
            response.raise_for_status()
            rows = _extract_list(response.json())
            if rows:
                return rows
            last_error = "Provider returned no transcript content."
        except requests.exceptions.RequestException as exc:
            last_error = str(exc)
    if last_error:
        raise requests.exceptions.RequestException(last_error)
    return []


def get_earnings_transcript_snapshot(
    ticker: str,
    lookback_quarters: int = 2
) -> dict:
    normalized_ticker = str(ticker or "").strip().upper()
    api_key = _get_fmp_api_key()
    if not api_key:
        unavailable_quality = score_earnings_quality({"ok": False, "ticker": normalized_ticker}, {"guidance_label": "unavailable"})
        return _response(
            False,
            normalized_ticker,
            source=SOURCE_UNAVAILABLE,
            data={
                "transcripts": [],
                "transcript_analysis": {"ok": False, "ticker": normalized_ticker, "error": "FMP_API_KEY is not configured."},
                "guidance_context": {"ok": False, "ticker": normalized_ticker, "guidance_label": "unavailable", "error": "FMP_API_KEY is not configured."},
                "earnings_quality": unavailable_quality,
                "earnings_summary": {"ticker": normalized_ticker, "summary": "Earnings transcript context is unavailable."},
            },
            error="FMP_API_KEY is not configured.",
        )

    try:
        date_rows = _fetch_fmp_transcript_dates(normalized_ticker, api_key=api_key)
        selected_dates = []
        seen_pairs: set[tuple[Any, Any]] = set()
        for row in date_rows:
            year = row.get("year") or row.get("fiscalYear")
            quarter = row.get("quarter") or row.get("fiscalQuarter")
            if (year, quarter) in seen_pairs or year is None or quarter is None:
                continue
            seen_pairs.add((year, quarter))
            selected_dates.append({"year": year, "quarter": quarter})
            if len(selected_dates) >= max(int(lookback_quarters or 0), 1):
                break

        transcripts: list[dict] = []
        for item in selected_dates:
            rows = _fetch_fmp_transcript(normalized_ticker, item["year"], item["quarter"], api_key=api_key)
            if rows:
                transcripts.append(normalize_transcript_item(rows[0]))

        if not transcripts:
            unavailable_quality = score_earnings_quality({"ok": False, "ticker": normalized_ticker}, {"guidance_label": "unavailable"})
            return _response(
                False,
                normalized_ticker,
                source=SOURCE_FMP,
                data={
                    "transcripts": [],
                    "transcript_analysis": {"ok": False, "ticker": normalized_ticker, "error": "No recent earnings transcripts were returned."},
                    "guidance_context": {"ok": False, "ticker": normalized_ticker, "guidance_label": "unavailable", "error": "No recent earnings transcripts were returned."},
                    "earnings_quality": unavailable_quality,
                    "earnings_summary": {"ticker": normalized_ticker, "summary": "Earnings transcript context is unavailable."},
                },
                error="No recent earnings transcripts were returned.",
            )

        transcript_analysis = analyze_transcript_sentiment(transcripts)
        guidance_context = analyze_guidance_context(transcripts)
        earnings_quality = score_earnings_quality(transcript_analysis, guidance_context)
        earnings_summary = summarize_earnings_context(normalized_ticker, transcripts, transcript_analysis, guidance_context)
        return _response(
            True,
            normalized_ticker,
            source=SOURCE_FMP,
            data={
                "transcripts": transcripts,
                "transcript_analysis": transcript_analysis,
                "guidance_context": guidance_context,
                "earnings_quality": earnings_quality,
                "earnings_summary": earnings_summary,
            },
        )
    except requests.exceptions.RequestException as exc:
        unavailable_quality = score_earnings_quality({"ok": False, "ticker": normalized_ticker}, {"guidance_label": "unavailable"})
        return _response(
            False,
            normalized_ticker,
            source=SOURCE_FMP,
            data={
                "transcripts": [],
                "transcript_analysis": {"ok": False, "ticker": normalized_ticker, "error": str(exc)},
                "guidance_context": {"ok": False, "ticker": normalized_ticker, "guidance_label": "unavailable", "error": str(exc)},
                "earnings_quality": unavailable_quality,
                "earnings_summary": {"ticker": normalized_ticker, "summary": "Earnings transcript context is unavailable."},
            },
            error=f"Failed to fetch earnings transcripts: {exc}",
        )
    except Exception as exc:
        unavailable_quality = score_earnings_quality({"ok": False, "ticker": normalized_ticker}, {"guidance_label": "unavailable"})
        return _response(
            False,
            normalized_ticker,
            source=SOURCE_FMP,
            data={
                "transcripts": [],
                "transcript_analysis": {"ok": False, "ticker": normalized_ticker, "error": str(exc)},
                "guidance_context": {"ok": False, "ticker": normalized_ticker, "guidance_label": "unavailable", "error": str(exc)},
                "earnings_quality": unavailable_quality,
                "earnings_summary": {"ticker": normalized_ticker, "summary": "Earnings transcript context is unavailable."},
            },
            error=f"Unexpected error while fetching earnings transcripts: {exc}",
        )
