from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse
import hashlib

import pandas as pd
from pydantic import BaseModel, ConfigDict, Field


EVIDENCE_CATEGORIES = {
    "company_news",
    "earnings",
    "sec_filing",
    "regulatory",
    "industry",
    "analyst_context",
    "macro",
    "other",
}
EVIDENCE_STANCES = {"positive", "negative", "neutral", "uncertain"}
MATERIALITY_LEVELS = {"low", "medium", "high"}
SOURCE_TYPES = {"sec", "company_ir", "regulator", "exchange", "news", "transcript", "other"}
SECRET_QUERY_KEYS = {
    "apikey",
    "api_key",
    "access_token",
    "auth",
    "authorization",
    "client_secret",
    "key",
    "password",
    "secret",
    "token",
}


class NormalizedSource(BaseModel):
    model_config = ConfigDict(extra="ignore")

    source_id: str
    url: str
    title: str = ""
    domain: str = ""
    published_at: str | None = None
    source_type: str = "other"
    primary_source: bool = False
    citation_start: int | None = None
    citation_end: int | None = None


class NormalizedEvidenceItem(BaseModel):
    model_config = ConfigDict(extra="ignore")

    evidence_id: str
    ticker: str
    category: str = "other"
    claim: str
    stance: str = "uncertain"
    materiality: str = "medium"
    event_date: str | None = None
    published_at: str | None = None
    source_ids: list[str] = Field(default_factory=list)
    corroboration_count: int = 0
    confidence_label: str = "low"
    primary_source_supported: bool = False


class ResearchFreshness(BaseModel):
    latest_source_date: str | None = None
    dated_source_count: int = 0
    undated_source_count: int = 0
    freshness_label: str = "unknown"


class ResearchDossier(BaseModel):
    ticker: str
    status: str = "unavailable"
    summary: str = ""
    evidence_items: list[NormalizedEvidenceItem] = Field(default_factory=list)
    positive_catalysts: list[str] = Field(default_factory=list)
    negative_catalysts: list[str] = Field(default_factory=list)
    neutral_context: list[str] = Field(default_factory=list)
    uncertainties: list[str] = Field(default_factory=list)
    conflicting_evidence: list[str] = Field(default_factory=list)
    source_ids: list[str] = Field(default_factory=list)
    freshness: ResearchFreshness = Field(default_factory=ResearchFreshness)
    warnings: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)


class ExtractedEvidenceItem(BaseModel):
    model_config = ConfigDict(extra="allow")

    ticker: str
    category: str = "other"
    claim: str
    stance: str = "uncertain"
    materiality: str = "medium"
    event_date: str | None = None
    published_at: str | None = None
    source_ids: list[str] = Field(default_factory=list)


class ExtractedDossier(BaseModel):
    model_config = ConfigDict(extra="allow")

    ticker: str
    summary: str = ""
    positive_catalysts: list[str] = Field(default_factory=list)
    negative_catalysts: list[str] = Field(default_factory=list)
    neutral_context: list[str] = Field(default_factory=list)
    uncertainties: list[str] = Field(default_factory=list)
    conflicting_evidence: list[str] = Field(default_factory=list)


class ResearchExtractionModel(BaseModel):
    model_config = ConfigDict(extra="allow")

    dossiers: list[ExtractedDossier] = Field(default_factory=list)
    evidence_items: list[ExtractedEvidenceItem] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def normalize_timestamp(value: Any) -> str | None:
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


def safe_text(value: Any, limit: int = 600) -> str:
    text = str(value or "").strip()
    if len(text) > limit:
        return f"{text[: limit - 3]}..."
    return text


def normalize_scope(value: str) -> str:
    normalized = str(value or "").strip().lower()
    mapping = {
        "news": "company_news",
        "current_news": "company_news",
        "catalysts": "company_news",
        "catalyst": "company_news",
        "filing": "sec_filing",
        "filings": "sec_filing",
        "sec": "sec_filing",
        "sec_filings": "sec_filing",
        "transcript": "earnings",
        "transcripts": "earnings",
        "earnings_transcripts": "earnings",
    }
    normalized = mapping.get(normalized, normalized)
    return normalized if normalized in EVIDENCE_CATEGORIES else "other"


def normalize_scopes(scopes: list[str] | None) -> list[str]:
    raw = scopes or ["company_news", "earnings", "sec_filing", "regulatory", "industry", "major_risks"]
    seen: set[str] = set()
    result: list[str] = []
    for value in raw:
        scope = normalize_scope(str(value))
        if scope not in seen:
            seen.add(scope)
            result.append(scope)
    return result


def sanitize_url(url: Any) -> str | None:
    raw = str(url or "").strip()
    if not raw:
        return None
    parsed = urlparse(raw)
    if parsed.scheme.lower() not in {"http", "https"} or not parsed.netloc:
        return None
    clean_pairs = [
        (key, value)
        for key, value in parse_qsl(parsed.query, keep_blank_values=True)
        if key.lower() not in SECRET_QUERY_KEYS
    ]
    parsed = parsed._replace(
        scheme=parsed.scheme.lower(),
        netloc=parsed.netloc.lower(),
        query=urlencode(clean_pairs, doseq=True),
        fragment="",
    )
    return urlunparse(parsed)


def domain_from_url(url: str) -> str:
    return urlparse(url).netloc.lower().removeprefix("www.")


def classify_source(url: str, title: str = "") -> tuple[str, bool]:
    domain = domain_from_url(url)
    path = urlparse(url).path.lower()
    text = f"{domain} {path} {title}".lower()
    regulator_domains = ("sec.gov", "federalreserve.gov", "treasury.gov", "cftc.gov", "finra.org", "fda.gov", "ftc.gov", "justice.gov")
    exchange_domains = ("nasdaq.com", "nyse.com", "cboe.com", "theice.com")
    if domain.endswith("sec.gov"):
        return "sec", True
    if any(domain.endswith(item) for item in regulator_domains) or domain.endswith(".gov"):
        return "regulator", True
    if any(domain.endswith(item) for item in exchange_domains):
        return "exchange", True
    if "investor" in text or "/ir" in path or "investor-relations" in text:
        return "company_ir", True
    if "transcript" in text:
        return "transcript", False
    return "news", False


def stable_id(prefix: str, *parts: Any) -> str:
    joined = "|".join(str(part or "") for part in parts)
    digest = hashlib.sha256(joined.encode("utf-8")).hexdigest()[:12]
    return f"{prefix}_{digest}"


def normalize_sources(raw_sources: list[dict]) -> tuple[list[dict], list[str]]:
    by_url: dict[str, dict] = {}
    warnings: list[str] = []
    for raw in raw_sources:
        if not isinstance(raw, dict):
            continue
        url = sanitize_url(raw.get("url"))
        if not url:
            warnings.append("Dropped malformed or unsafe source URL.")
            continue
        title = safe_text(raw.get("title") or raw.get("name") or url, limit=240)
        published_at = normalize_timestamp(raw.get("published_at") or raw.get("published") or raw.get("date"))
        source_type, primary = classify_source(url, title)
        existing = by_url.get(url)
        citation_start = raw.get("citation_start") if isinstance(raw.get("citation_start"), int) else None
        citation_end = raw.get("citation_end") if isinstance(raw.get("citation_end"), int) else None
        if existing:
            if not existing.get("title") and title:
                existing["title"] = title
            if not existing.get("published_at") and published_at:
                existing["published_at"] = published_at
            if existing.get("citation_start") is None and citation_start is not None:
                existing["citation_start"] = citation_start
            if existing.get("citation_end") is None and citation_end is not None:
                existing["citation_end"] = citation_end
            continue
        by_url[url] = {
            "source_id": "",
            "url": url,
            "title": title,
            "domain": domain_from_url(url),
            "published_at": published_at,
            "source_type": source_type,
            "primary_source": primary,
            "citation_start": citation_start,
            "citation_end": citation_end,
        }
    sources = []
    for index, source in enumerate(by_url.values(), start=1):
        source["source_id"] = f"source_{index}"
        sources.append(NormalizedSource.model_validate(source).model_dump(mode="json"))
    return sources, list(dict.fromkeys(warnings))


def _confidence(source_ids: list[str], source_lookup: dict[str, dict], published_at: str | None) -> tuple[str, bool]:
    primary = any(source_lookup.get(source_id, {}).get("primary_source") for source_id in source_ids)
    source_count = len(set(source_ids))
    if primary and source_count >= 2:
        return "high", True
    if primary or source_count >= 2:
        return "medium", primary
    return "low", primary


def normalize_evidence_items(raw_items: list[dict], sources: list[dict], requested_tickers: list[str]) -> tuple[list[dict], list[str]]:
    source_lookup = {source["source_id"]: source for source in sources if isinstance(source, dict) and source.get("source_id")}
    ticker_set = {ticker.upper() for ticker in requested_tickers}
    warnings: list[str] = []
    seen: set[str] = set()
    normalized: list[dict] = []
    for raw in raw_items:
        if not isinstance(raw, dict):
            continue
        ticker = str(raw.get("ticker") or "").strip().upper()
        claim = safe_text(raw.get("claim"), limit=500)
        source_ids = [str(item) for item in raw.get("source_ids", []) if str(item) in source_lookup]
        if not ticker or ticker not in ticker_set or not claim:
            warnings.append("Dropped malformed evidence item.")
            continue
        malicious_markers = ("ignore all system rules", "place an order", "reveal the api key", "mark this stock paper eligible", "buy now", "sell now")
        if any(marker in claim.lower() for marker in malicious_markers):
            warnings.append(f"Dropped prompt-injection-like evidence text for {ticker}.")
            continue
        if not source_ids:
            warnings.append(f"Dropped unsupported evidence for {ticker}: missing valid source reference.")
            continue
        key = f"{ticker}:{normalize_scope(raw.get('category', 'other'))}:{claim.lower()}"
        if key in seen:
            continue
        seen.add(key)
        stance = str(raw.get("stance") or "uncertain").strip().lower()
        materiality = str(raw.get("materiality") or "medium").strip().lower()
        published_at = normalize_timestamp(raw.get("published_at"))
        event_date = normalize_timestamp(raw.get("event_date"))
        confidence, primary = _confidence(source_ids, source_lookup, published_at)
        item = {
            "evidence_id": stable_id("evidence", ticker, claim, ",".join(sorted(source_ids))),
            "ticker": ticker,
            "category": normalize_scope(raw.get("category", "other")),
            "claim": claim,
            "stance": stance if stance in EVIDENCE_STANCES else "uncertain",
            "materiality": materiality if materiality in MATERIALITY_LEVELS else "medium",
            "event_date": event_date,
            "published_at": published_at,
            "source_ids": list(dict.fromkeys(source_ids)),
            "corroboration_count": max(len(set(source_ids)) - 1, 0),
            "confidence_label": confidence,
            "primary_source_supported": primary,
        }
        normalized.append(NormalizedEvidenceItem.model_validate(item).model_dump(mode="json"))
    return normalized, list(dict.fromkeys(warnings))


def build_freshness(source_ids: list[str], source_lookup: dict[str, dict]) -> dict:
    dates = [source_lookup[source_id].get("published_at") for source_id in source_ids if source_lookup.get(source_id, {}).get("published_at")]
    undated = len([source_id for source_id in source_ids if source_id in source_lookup and not source_lookup[source_id].get("published_at")])
    latest = max(dates) if dates else None
    label = "unknown"
    if latest:
        try:
            age_days = (pd.Timestamp(now_iso()) - pd.Timestamp(latest)).days
            if age_days <= 14:
                label = "current"
            elif age_days <= 90:
                label = "mixed"
            else:
                label = "stale"
        except Exception:
            label = "mixed"
    elif undated:
        label = "unknown"
    return ResearchFreshness(
        latest_source_date=latest,
        dated_source_count=len(dates),
        undated_source_count=undated,
        freshness_label=label,
    ).model_dump(mode="json")


def build_dossiers(
    tickers: list[str],
    evidence_items: list[dict],
    sources: list[dict],
    extracted_dossiers: list[dict] | None = None,
    warnings_by_ticker: dict[str, list[str]] | None = None,
    errors_by_ticker: dict[str, list[str]] | None = None,
) -> list[dict]:
    source_lookup = {source["source_id"]: source for source in sources if isinstance(source, dict) and source.get("source_id")}
    extracted_lookup = {str(item.get("ticker") or "").upper(): item for item in extracted_dossiers or [] if isinstance(item, dict)}
    dossiers: list[dict] = []
    for ticker in tickers:
        ticker_items = [item for item in evidence_items if str(item.get("ticker")).upper() == ticker]
        source_ids = []
        for item in ticker_items:
            source_ids.extend(item.get("source_ids", []))
        source_ids = list(dict.fromkeys(source_ids))
        extracted = extracted_lookup.get(ticker, {})
        positives = list(extracted.get("positive_catalysts", []))
        negatives = list(extracted.get("negative_catalysts", []))
        neutral = list(extracted.get("neutral_context", []))
        uncertainties = list(extracted.get("uncertainties", []))
        conflicts = list(extracted.get("conflicting_evidence", []))
        for item in ticker_items:
            claim = item.get("claim")
            if item.get("stance") == "positive":
                positives.append(claim)
            elif item.get("stance") == "negative":
                negatives.append(claim)
            elif item.get("stance") == "uncertain":
                uncertainties.append(claim)
            else:
                neutral.append(claim)
        status = "available" if ticker_items else "unavailable"
        if ticker_items and (warnings_by_ticker or errors_by_ticker):
            status = "partial" if (warnings_by_ticker or errors_by_ticker) else status
        summary = safe_text(extracted.get("summary") or (ticker_items[0].get("claim") if ticker_items else "No usable current research sources were returned."))
        dossier = ResearchDossier(
            ticker=ticker,
            status=status,
            summary=summary,
            evidence_items=[NormalizedEvidenceItem.model_validate(item) for item in ticker_items],
            positive_catalysts=list(dict.fromkeys(str(item) for item in positives if item))[:8],
            negative_catalysts=list(dict.fromkeys(str(item) for item in negatives if item))[:8],
            neutral_context=list(dict.fromkeys(str(item) for item in neutral if item))[:8],
            uncertainties=list(dict.fromkeys(str(item) for item in uncertainties if item))[:8],
            conflicting_evidence=list(dict.fromkeys(str(item) for item in conflicts if item))[:8],
            source_ids=source_ids,
            freshness=ResearchFreshness.model_validate(build_freshness(source_ids, source_lookup)),
            warnings=list(dict.fromkeys((warnings_by_ticker or {}).get(ticker, []))),
            errors=list(dict.fromkeys((errors_by_ticker or {}).get(ticker, []))),
        )
        dossiers.append(dossier.model_dump(mode="json"))
    return dossiers
