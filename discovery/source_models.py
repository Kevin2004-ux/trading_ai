from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any


DISCOVERY_VERSION = "candidate_discovery_v1"
MAX_DISCOVERED_TICKERS = 100
TOP_DISCOVERY_CANDIDATES = 5


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def unique_texts(values: list[Any] | None) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values or []:
        text = str(value or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        result.append(text)
    return result


def safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _compact_candidate(row: dict[str, Any]) -> dict[str, Any]:
    sources = row.get("sources")
    source_type = row.get("source_type")
    reasons = unique_texts(row.get("reasons"))
    compact = {
        "ticker": str(row.get("ticker") or "").strip().upper(),
        "discovery_score": safe_float(row.get("discovery_score")),
        "requires_live_validation": bool(row.get("requires_live_validation", True)),
        "point_in_time_safe": bool(row.get("point_in_time_safe", True)),
        "reasons": reasons,
        "reason_discovered": reasons[0] if reasons else None,
    }
    if isinstance(sources, list) and sources:
        compact["sources"] = unique_texts(sources)
    else:
        compact["source_type"] = str(source_type or "").strip() or None
    catalyst_type = str(row.get("catalyst_type") or "").strip().lower()
    if catalyst_type:
        compact["catalyst_type"] = catalyst_type
    catalyst_types = unique_texts(row.get("catalyst_types"))
    if catalyst_types:
        compact["catalyst_types"] = catalyst_types
    external_sources = unique_texts(row.get("external_sources"))
    if external_sources:
        compact["external_sources"] = external_sources
    headline = str(row.get("headline") or row.get("title") or "").strip()
    if headline:
        compact["headline"] = headline
    if row.get("url"):
        compact["url"] = row.get("url")
    if row.get("published_at"):
        compact["published_at"] = row.get("published_at")
    if row.get("as_of"):
        compact["as_of"] = row.get("as_of")
    confidence = row.get("confidence")
    if confidence is not None:
        compact["confidence"] = max(0.0, min(1.0, safe_float(confidence)))
    return compact


def summarize_discovery_result(
    discovery_result: dict[str, Any] | None,
    *,
    top_limit: int = TOP_DISCOVERY_CANDIDATES,
) -> dict[str, Any]:
    payload = discovery_result if isinstance(discovery_result, dict) else {}
    candidates = [item for item in payload.get("candidates", []) if isinstance(item, dict)]
    tickers = [
        str(item or "").strip().upper()
        for item in payload.get("tickers", [])
        if str(item or "").strip()
    ]
    if not tickers:
        tickers = [str(item.get("ticker") or "").strip().upper() for item in candidates if str(item.get("ticker") or "").strip()]
    discovered_count = safe_int(payload.get("discovered_count"), len(tickers))
    candidate_catalyst_types = [item.get("catalyst_type") for item in candidates]
    candidate_catalyst_types.extend(
        nested
        for item in candidates
        for nested in (item.get("catalyst_types") if isinstance(item.get("catalyst_types"), list) else [])
    )
    candidate_catalyst_sources = [
        source
        for item in candidates
        for source in (item.get("external_sources") if isinstance(item.get("external_sources"), list) else [])
    ]
    if not candidate_catalyst_sources:
        candidate_catalyst_sources = [item.get("source") for item in candidates if item.get("source_type") == "external_catalyst"]
    catalyst_types = unique_texts(payload.get("catalyst_types") or candidate_catalyst_types)
    catalyst_sources = unique_texts(payload.get("catalyst_sources_used") or candidate_catalyst_sources)
    return {
        "discovery_used": bool(payload.get("discovery_used", False)),
        "external_discovery_used": bool(payload.get("external_discovery_used") or catalyst_sources),
        "discovered_count": discovered_count,
        "sources_used": unique_texts(payload.get("sources_used")),
        "requested_sources": unique_texts(payload.get("requested_sources")),
        "catalyst_sources_used": catalyst_sources,
        "catalyst_types": catalyst_types,
        "tickers": tickers[: MAX_DISCOVERED_TICKERS],
        "top_candidates": [_compact_candidate(row) for row in candidates[: max(1, top_limit)]],
        "warnings": unique_texts(payload.get("warnings")),
        "errors": unique_texts(payload.get("errors")),
        "external_discovery": payload.get("external_discovery") if isinstance(payload.get("external_discovery"), dict) else {},
        "fallback_used": bool(payload.get("fallback_used", False)),
        "bypass_reason": payload.get("bypass_reason"),
        "point_in_time_safe": bool(payload.get("point_in_time_safe", True)),
        "requires_live_validation": bool(payload.get("requires_live_validation", True)),
    }


@dataclass
class DiscoveryCandidate:
    ticker: str
    source: str
    source_type: str
    discovered_at: str
    as_of: str
    discovery_score: float
    reasons: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    raw_metadata: dict[str, Any] = field(default_factory=dict)
    point_in_time_safe: bool = True
    requires_live_validation: bool = True

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["ticker"] = str(payload["ticker"]).strip().upper()
        payload["discovery_score"] = safe_float(payload.get("discovery_score"))
        payload["reasons"] = unique_texts(payload.get("reasons"))
        payload["warnings"] = unique_texts(payload.get("warnings"))
        return payload


def empty_discovery_result(
    *,
    requested_sources: list[str] | None = None,
    warnings: list[str] | None = None,
    errors: list[str] | None = None,
    discovered_at: str | None = None,
    discovery_used: bool = False,
    fallback_used: bool = False,
    bypass_reason: str | None = None,
) -> dict[str, Any]:
    timestamp = discovered_at or utc_now_iso()
    return {
        "ok": True,
        "discovery_version": DISCOVERY_VERSION,
        "discovered_at": timestamp,
        "as_of": timestamp,
        "requested_sources": requested_sources or [],
        "sources_used": [],
        "candidates": [],
        "tickers": [],
        "discovered_count": 0,
        "warnings": unique_texts(warnings),
        "errors": unique_texts(errors),
        "point_in_time_safe": True,
        "requires_live_validation": True,
        "discovery_used": discovery_used,
        "fallback_used": fallback_used,
        "bypass_reason": bypass_reason,
    }
