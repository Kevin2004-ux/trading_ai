from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from importlib.util import find_spec
from threading import RLock
from typing import Any
import os
import time
import uuid

from scanner.universe_builder import validate_ticker_universe
from realtime.catalyst_enrichment import get_catalyst_snapshot

from .earnings_transcripts import get_earnings_transcript_snapshot
from .evidence_models import (
    build_dossiers,
    normalize_evidence_items,
    normalize_scope,
    normalize_scopes,
    normalize_sources,
    now_iso,
    safe_text,
    stable_id,
)
from .news_provider import diagnose_news_provider, fetch_recent_news
from .sec_filings import get_sec_filing_snapshot
from .web_research_provider import get_research_model, is_openai_research_available, research_with_openai_web


CURRENT_RESEARCH_VERSION = "current_research_v1"
DEFAULT_RESEARCH_MAX_TICKERS = 3
DEFAULT_RESEARCH_MAX_SOURCES = 12
DEFAULT_RESEARCH_CACHE_TTL_SECONDS = 900
RESEARCH_CACHE_MAX_ENTRIES = 64

_CACHE_LOCK = RLock()
_RESEARCH_CACHE: dict[tuple, tuple[float, dict]] = {}


def _as_dict(value: Any) -> dict:
    return value if isinstance(value, dict) else {}


def _as_list(value: Any) -> list:
    return value if isinstance(value, list) else []


def _bool_env(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return str(value).strip().lower() in {"1", "true", "yes", "y", "on"}


def _int_env(name: str, default: int, min_value: int = 1, max_value: int = 100) -> int:
    try:
        value = int(os.getenv(name, default))
    except (TypeError, ValueError):
        return default
    return max(min_value, min(max_value, value))


def _provider(provider: str | None = None) -> str:
    requested = str(provider or os.getenv("AI_RESEARCH_PROVIDER") or "auto").strip().lower()
    return requested if requested in {"auto", "openai", "local", "disabled"} else "auto"


def _ttl_seconds() -> int:
    return _int_env("RESEARCH_CACHE_TTL_SECONDS", DEFAULT_RESEARCH_CACHE_TTL_SECONDS, min_value=0, max_value=86400)


def _max_tickers() -> int:
    return _int_env("OPENAI_RESEARCH_MAX_TICKERS", DEFAULT_RESEARCH_MAX_TICKERS, min_value=1, max_value=20)


def _max_sources() -> int:
    return _int_env("OPENAI_RESEARCH_MAX_SOURCES", DEFAULT_RESEARCH_MAX_SOURCES, min_value=1, max_value=50)


def _date_bucket(as_of: str | None) -> str:
    if as_of:
        return str(as_of)[:10]
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def clear_research_cache() -> None:
    with _CACHE_LOCK:
        _RESEARCH_CACHE.clear()


def _cache_key(tickers: list[str], scopes: list[str], provider: str, model: str | None, as_of: str | None) -> tuple:
    return (tuple(tickers), tuple(scopes), provider, model or "", _date_bucket(as_of))


def _cache_get(key: tuple) -> dict | None:
    ttl = _ttl_seconds()
    if ttl <= 0:
        return None
    now = time.time()
    with _CACHE_LOCK:
        item = _RESEARCH_CACHE.get(key)
        if not item:
            return None
        created_at, payload = item
        if now - created_at > ttl:
            _RESEARCH_CACHE.pop(key, None)
            return None
        cached = deepcopy(payload)
        cached["cache_hit"] = True
        return cached


def _cache_set(key: tuple, payload: dict) -> None:
    ttl = _ttl_seconds()
    if ttl <= 0:
        return
    if payload.get("status") == "failed":
        return
    text = f"{payload.get('warnings')} {payload.get('errors')}".lower()
    if "authentication" in text or "api key" in text or "unauthorized" in text:
        return
    with _CACHE_LOCK:
        if len(_RESEARCH_CACHE) >= RESEARCH_CACHE_MAX_ENTRIES:
            oldest_key = min(_RESEARCH_CACHE, key=lambda item: _RESEARCH_CACHE[item][0])
            _RESEARCH_CACHE.pop(oldest_key, None)
        copy = deepcopy(payload)
        copy["cache_hit"] = False
        _RESEARCH_CACHE[key] = (time.time(), copy)


def _usage() -> dict:
    return {"input_tokens": None, "output_tokens": None, "total_tokens": None, "web_search_calls": 0, "extraction_calls": 0}


def empty_research_response(
    *,
    status: str = "disabled",
    provider: str = "none",
    request_id: str | None = None,
    as_of: str | None = None,
    tickers: list[str] | None = None,
    scopes: list[str] | None = None,
    warnings: list[str] | None = None,
    errors: list[str] | None = None,
) -> dict:
    return {
        "ok": status in {"disabled", "unavailable"},
        "research_version": CURRENT_RESEARCH_VERSION,
        "status": status,
        "provider": provider,
        "model": None,
        "request_id": request_id,
        "as_of": as_of or now_iso(),
        "web_search_used": False,
        "local_research_used": False,
        "cache_hit": False,
        "tickers_requested": tickers or [],
        "tickers_researched": [],
        "scopes_requested": scopes or [],
        "dossiers": [],
        "sources": [],
        "warnings": warnings or [],
        "errors": errors or [],
        "usage": _usage(),
    }


def get_research_runtime_status(provider: str | None = None) -> dict:
    requested = _provider(provider)
    sec_enabled = _bool_env("SEC_RESEARCH_ENABLED", _bool_env("ENABLE_SEC_RESEARCH", True))
    sec_available = bool(sec_enabled and os.getenv("SEC_USER_AGENT"))
    news_enabled = _bool_env("NEWS_RESEARCH_ENABLED", False)
    return {
        "ai_research_provider": requested,
        "openai_research_configured": bool(os.getenv("OPENAI_API_KEY")),
        "openai_research_sdk_available": find_spec("openai") is not None,
        "openai_research_model": get_research_model(),
        "ai_research_available": requested != "disabled" and is_openai_research_available(),
        "local_news_research_available": news_enabled,
        "sec_research_available": sec_available,
        "research_max_tickers": _max_tickers(),
    }


def _normalize_tickers(tickers: list[str]) -> tuple[list[str], list[str]]:
    validation = validate_ticker_universe(tickers, max_tickers=_max_tickers())
    if isinstance(validation, dict) and validation.get("ok"):
        return validation.get("tickers", []), []
    errors = validation.get("errors", []) if isinstance(validation, dict) else ["Ticker validation failed."]
    return validation.get("tickers", []) if isinstance(validation, dict) else [], [str(item) for item in errors]


def _raw_source(url: Any, title: Any, published_at: Any = None) -> dict | None:
    if not url:
        return None
    return {"url": url, "title": title or url, "published_at": published_at}


def _local_news(ticker: str, warnings: list[str]) -> tuple[list[dict], list[dict]]:
    sources: list[dict] = []
    evidence: list[dict] = []
    try:
        news = fetch_recent_news(ticker, limit=5)
    except Exception as exc:
        warnings.append(f"Local news research failed for {ticker}: {safe_text(exc, 160)}")
        return sources, evidence
    warnings.extend(str(item) for item in _as_list(news.get("warnings")))
    warnings.extend(str(item) for item in _as_list(news.get("errors")))
    for article in _as_list(news.get("articles")):
        raw = _raw_source(article.get("url"), article.get("title") or article.get("headline"), article.get("published_at") or article.get("publishedDate"))
        if raw:
            sources.append(raw)
            claim = article.get("summary") or article.get("title") or article.get("headline")
            evidence.append(
                {
                    "ticker": ticker,
                    "category": "company_news",
                    "claim": safe_text(claim, 300),
                    "stance": str(article.get("sentiment") or "neutral").lower(),
                    "materiality": "medium",
                    "published_at": article.get("published_at") or article.get("publishedDate"),
                    "source_url": raw["url"],
                }
            )
    return sources, evidence


def _local_catalyst(ticker: str, warnings: list[str]) -> tuple[list[dict], list[dict]]:
    sources: list[dict] = []
    evidence: list[dict] = []
    try:
        result = get_catalyst_snapshot(ticker, lookback_days=7)
    except Exception as exc:
        warnings.append(f"Local catalyst research failed for {ticker}: {safe_text(exc, 160)}")
        return sources, evidence
    if result.get("error"):
        warnings.append(str(result.get("error")))
    data = _as_dict(result.get("data"))
    news_snapshot = _as_dict(data.get("news_snapshot"))
    catalyst_score = _as_dict(data.get("catalyst_score"))
    for item in _as_list(news_snapshot.get("items")):
        raw = _raw_source(item.get("url"), item.get("title"), item.get("published_at"))
        if raw:
            sources.append(raw)
            evidence.append(
                {
                    "ticker": ticker,
                    "category": "company_news",
                    "claim": item.get("summary") or item.get("title"),
                    "stance": str(item.get("sentiment") or "neutral").lower(),
                    "materiality": "medium",
                    "published_at": item.get("published_at"),
                    "source_url": raw["url"],
                }
            )
    first_source = sources[0]["url"] if sources else None
    if first_source and catalyst_score.get("summary"):
        label = str(catalyst_score.get("catalyst_label") or "neutral").lower()
        evidence.append(
            {
                "ticker": ticker,
                "category": "company_news",
                "claim": catalyst_score.get("summary"),
                "stance": "positive" if "positive" in label else "negative" if label in {"negative", "high_risk"} else "neutral",
                "materiality": "medium",
                "source_url": first_source,
            }
        )
    return sources, evidence


def _local_sec(ticker: str, warnings: list[str]) -> tuple[list[dict], list[dict]]:
    sources: list[dict] = []
    evidence: list[dict] = []
    try:
        result = get_sec_filing_snapshot(ticker)
    except Exception as exc:
        warnings.append(f"Local SEC research failed for {ticker}: {safe_text(exc, 160)}")
        return sources, evidence
    if result.get("error"):
        warnings.append(str(result.get("error")))
    data = _as_dict(result.get("data"))
    analysis = _as_dict(data.get("filing_analysis"))
    for filing in _as_list(data.get("filings")):
        raw = _raw_source(filing.get("url") or filing.get("filing_url"), filing.get("title") or filing.get("filing_type"), filing.get("filed_at") or filing.get("filing_date"))
        if raw:
            sources.append(raw)
    first_source = sources[0]["url"] if sources else None
    for claim in _as_list(analysis.get("positive_filing_signals")):
        evidence.append({"ticker": ticker, "category": "sec_filing", "claim": claim, "stance": "positive", "materiality": "medium", "source_url": first_source})
    for claim in _as_list(analysis.get("negative_filing_signals")) + _as_list(analysis.get("risk_flags")):
        evidence.append({"ticker": ticker, "category": "sec_filing", "claim": claim, "stance": "negative", "materiality": "high", "source_url": first_source})
    if first_source and analysis.get("summary") and not evidence:
        evidence.append({"ticker": ticker, "category": "sec_filing", "claim": analysis.get("summary"), "stance": "neutral", "materiality": "medium", "source_url": first_source})
    return sources, evidence


def _local_earnings(ticker: str, warnings: list[str]) -> tuple[list[dict], list[dict]]:
    sources: list[dict] = []
    evidence: list[dict] = []
    try:
        result = get_earnings_transcript_snapshot(ticker)
    except Exception as exc:
        warnings.append(f"Local earnings research failed for {ticker}: {safe_text(exc, 160)}")
        return sources, evidence
    if result.get("error"):
        warnings.append(str(result.get("error")))
    data = _as_dict(result.get("data"))
    quality = _as_dict(data.get("earnings_quality"))
    for transcript in _as_list(data.get("transcripts")):
        raw = _raw_source(transcript.get("url"), transcript.get("title"), transcript.get("reported_at"))
        if raw:
            sources.append(raw)
    first_source = sources[0]["url"] if sources else None
    for claim in _as_list(quality.get("positive_signals")):
        evidence.append({"ticker": ticker, "category": "earnings", "claim": claim, "stance": "positive", "materiality": "medium", "source_url": first_source})
    for claim in _as_list(quality.get("negative_signals")) + _as_list(quality.get("risk_flags")):
        evidence.append({"ticker": ticker, "category": "earnings", "claim": claim, "stance": "negative", "materiality": "high", "source_url": first_source})
    if first_source and quality.get("summary") and not evidence:
        evidence.append({"ticker": ticker, "category": "earnings", "claim": quality.get("summary"), "stance": "neutral", "materiality": "medium", "source_url": first_source})
    return sources, evidence


def _run_local_research(tickers: list[str], scopes: list[str]) -> dict:
    raw_sources: list[dict] = []
    raw_evidence: list[dict] = []
    warnings: list[str] = []
    for ticker in tickers:
        if "company_news" in scopes:
            sources, evidence = _local_news(ticker, warnings)
            raw_sources.extend(sources)
            raw_evidence.extend(evidence)
            sources, evidence = _local_catalyst(ticker, warnings)
            raw_sources.extend(sources)
            raw_evidence.extend(evidence)
        if "sec_filing" in scopes:
            sources, evidence = _local_sec(ticker, warnings)
            raw_sources.extend(sources)
            raw_evidence.extend(evidence)
        if "earnings" in scopes:
            sources, evidence = _local_earnings(ticker, warnings)
            raw_sources.extend(sources)
            raw_evidence.extend(evidence)
    normalized_sources, source_warnings = normalize_sources(raw_sources)
    source_by_url = {source["url"]: source["source_id"] for source in normalized_sources}
    evidence_with_ids = []
    for item in raw_evidence:
        source_id = source_by_url.get(item.pop("source_url", None))
        if source_id:
            evidence_with_ids.append({**item, "source_ids": [source_id]})
    normalized_evidence, evidence_warnings = normalize_evidence_items(evidence_with_ids, normalized_sources, tickers)
    return {
        "ok": bool(normalized_evidence),
        "sources": normalized_sources,
        "evidence_items": normalized_evidence,
        "warnings": list(dict.fromkeys(warnings + source_warnings + evidence_warnings)),
        "errors": [],
    }


def _merge_sources(source_groups: list[list[dict]]) -> tuple[list[dict], dict[str, str], list[str]]:
    raw = []
    old_to_url: dict[str, str] = {}
    for group in source_groups:
        for source in group:
            if isinstance(source, dict):
                old_to_url[source.get("source_id", "")] = source.get("url", "")
                raw.append(source)
    merged, warnings = normalize_sources(raw)
    url_to_new = {source["url"]: source["source_id"] for source in merged}
    old_to_new = {old_id: url_to_new[url] for old_id, url in old_to_url.items() if url in url_to_new}
    return merged, old_to_new, warnings


def _remap_evidence(evidence_groups: list[list[dict]], old_to_new: dict[str, str]) -> list[dict]:
    rows = []
    for group in evidence_groups:
        for item in group:
            if not isinstance(item, dict):
                continue
            source_ids = [old_to_new[source_id] for source_id in item.get("source_ids", []) if source_id in old_to_new]
            if source_ids:
                rows.append({**item, "source_ids": source_ids})
    return rows


def _overall_status(provider: str, evidence: list[dict], warnings: list[str], errors: list[str], web_used: bool, local_used: bool) -> tuple[bool, str, str]:
    if errors and not evidence:
        return False, "failed", provider
    if evidence and warnings:
        resolved_provider = "hybrid" if web_used and local_used else "openai_web" if web_used else "local"
        return True, "partial", resolved_provider
    if evidence:
        resolved_provider = "hybrid" if web_used and local_used else "openai_web" if web_used else "local"
        return True, "available", resolved_provider
    return False, "unavailable", provider if provider != "auto" else "none"


def build_current_research(
    tickers: list[str],
    scopes: list[str] | None = None,
    candidate_context: list[dict] | None = None,
    request_id: str | None = None,
    as_of: str | None = None,
    provider: str | None = None,
) -> dict:
    requested_provider = _provider(provider)
    normalized_scopes = normalize_scopes(scopes)
    normalized_tickers, ticker_errors = _normalize_tickers(tickers)
    requested_tickers = [str(ticker or "").strip().upper() for ticker in tickers if str(ticker or "").strip()]
    resolved_request_id = request_id or str(uuid.uuid4())
    as_of_value = as_of or now_iso()

    if requested_provider == "disabled":
        return empty_research_response(
            status="disabled",
            provider="none",
            request_id=resolved_request_id,
            as_of=as_of_value,
            tickers=requested_tickers,
            scopes=normalized_scopes,
            warnings=["Current research is disabled."],
        )
    if ticker_errors:
        return empty_research_response(
            status="failed",
            provider=requested_provider,
            request_id=resolved_request_id,
            as_of=as_of_value,
            tickers=requested_tickers,
            scopes=normalized_scopes,
            errors=ticker_errors,
        )
    if not normalized_tickers:
        return empty_research_response(
            status="unavailable",
            provider=requested_provider,
            request_id=resolved_request_id,
            as_of=as_of_value,
            tickers=requested_tickers,
            scopes=normalized_scopes,
            warnings=["No valid tickers were provided for current research."],
        )

    normalized_tickers = normalized_tickers[: _max_tickers()]
    model = get_research_model() if requested_provider in {"auto", "openai"} else None
    cache_key = _cache_key(normalized_tickers, normalized_scopes, requested_provider, model, as_of_value)
    cached = _cache_get(cache_key)
    if cached:
        return cached

    source_groups: list[list[dict]] = []
    evidence_groups: list[list[dict]] = []
    extracted_dossiers: list[dict] = []
    warnings: list[str] = []
    errors: list[str] = []
    usage = _usage()
    web_used = False
    local_used = False

    if requested_provider in {"auto", "local", "openai"} and requested_provider != "openai":
        local = _run_local_research(normalized_tickers, normalized_scopes)
        local_used = bool(local.get("ok"))
        source_groups.append(local.get("sources", []))
        evidence_groups.append(local.get("evidence_items", []))
        warnings.extend(local.get("warnings", []))
        errors.extend(local.get("errors", []))

    if requested_provider in {"auto", "openai"}:
        web = research_with_openai_web(
            normalized_tickers,
            scopes=normalized_scopes,
            candidate_context=candidate_context,
            request_id=resolved_request_id,
            as_of=as_of_value,
        )
        web_used = bool(web.get("web_search_used"))
        source_groups.append(web.get("sources", []))
        evidence_groups.append(web.get("evidence_items", []))
        extracted_dossiers.extend(web.get("extracted_dossiers", []))
        warnings.extend(web.get("warnings", []))
        errors.extend(web.get("errors", []))
        for key in ("web_search_calls", "extraction_calls"):
            usage[key] = usage.get(key, 0) + int(web.get("usage", {}).get(key) or 0)
        for key in ("input_tokens", "output_tokens", "total_tokens"):
            value = web.get("usage", {}).get(key)
            if value is not None:
                usage[key] = (usage[key] or 0) + value

        if requested_provider == "openai" and not web.get("ok"):
            local = _run_local_research(normalized_tickers, normalized_scopes)
            local_used = bool(local.get("ok"))
            source_groups.append(local.get("sources", []))
            evidence_groups.append(local.get("evidence_items", []))
            warnings.extend(local.get("warnings", []))
            errors.extend(local.get("errors", []))

    sources, old_to_new, source_warnings = _merge_sources(source_groups)
    sources = sources[: _max_sources()]
    valid_source_ids = {source["source_id"] for source in sources}
    evidence = [item for item in _remap_evidence(evidence_groups, old_to_new) if set(item.get("source_ids", [])).issubset(valid_source_ids)]
    evidence, evidence_warnings = normalize_evidence_items(evidence, sources, normalized_tickers)
    warnings.extend(source_warnings + evidence_warnings)
    dossiers = build_dossiers(normalized_tickers, evidence, sources, extracted_dossiers)
    ok, status, resolved_provider = _overall_status(requested_provider, evidence, warnings, errors, web_used, local_used)
    result = {
        "ok": ok,
        "research_version": CURRENT_RESEARCH_VERSION,
        "status": status,
        "provider": resolved_provider,
        "model": model if web_used or requested_provider in {"auto", "openai"} else None,
        "request_id": resolved_request_id,
        "as_of": as_of_value,
        "web_search_used": web_used,
        "local_research_used": local_used,
        "cache_hit": False,
        "tickers_requested": requested_tickers,
        "tickers_researched": [dossier["ticker"] for dossier in dossiers if dossier.get("status") in {"available", "partial"}],
        "scopes_requested": normalized_scopes,
        "dossiers": dossiers,
        "sources": sources,
        "warnings": list(dict.fromkeys(str(item) for item in warnings if item)),
        "errors": list(dict.fromkeys(str(item) for item in errors if item)),
        "usage": usage,
    }
    _cache_set(cache_key, result)
    return result


def scopes_from_research_preferences(research_preferences: dict | None) -> list[str]:
    preferences = _as_dict(research_preferences)
    scopes: list[str] = []
    if preferences.get("include_news"):
        scopes.append("company_news")
    if preferences.get("include_sec_filings"):
        scopes.append("sec_filing")
    if preferences.get("include_earnings_transcripts"):
        scopes.append("earnings")
    return [normalize_scope(scope) for scope in scopes]


__all__ = [
    "CURRENT_RESEARCH_VERSION",
    "build_current_research",
    "clear_research_cache",
    "empty_research_response",
    "get_research_runtime_status",
    "scopes_from_research_preferences",
]
