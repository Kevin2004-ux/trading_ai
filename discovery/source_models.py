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
    return {
        "discovery_used": bool(payload.get("discovery_used", False)),
        "discovered_count": discovered_count,
        "sources_used": unique_texts(payload.get("sources_used")),
        "requested_sources": unique_texts(payload.get("requested_sources")),
        "tickers": tickers[: MAX_DISCOVERED_TICKERS],
        "top_candidates": [_compact_candidate(row) for row in candidates[: max(1, top_limit)]],
        "warnings": unique_texts(payload.get("warnings")),
        "errors": unique_texts(payload.get("errors")),
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
