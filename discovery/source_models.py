from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any


DISCOVERY_VERSION = "candidate_discovery_v1"


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
    }
