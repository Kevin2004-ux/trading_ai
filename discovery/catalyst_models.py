from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from .source_models import safe_float, unique_texts, utc_now_iso


CATALYST_DISCOVERY_VERSION = "external_catalyst_discovery_v1"
MAX_PROVIDER_SEED_TICKERS = 12


@dataclass
class CatalystDiscoveryRequest:
    max_tickers: int
    discovered_at: str
    intent_constraints: dict[str, Any] = field(default_factory=dict)
    seed_tickers: list[str] = field(default_factory=list)


@dataclass
class CatalystProviderStatus:
    provider_name: str
    provider_type: str = "external_catalyst"
    configured: bool = False
    attempted: bool = False
    available: bool = False
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["warnings"] = unique_texts(payload.get("warnings"))
        payload["errors"] = unique_texts(payload.get("errors"))
        return payload


@dataclass
class CatalystCandidate:
    ticker: str
    source: str
    catalyst_type: str
    title: str
    discovered_at: str
    as_of: str
    discovery_score: float
    confidence: float = 0.5
    source_type: str = "external_catalyst"
    headline: str | None = None
    url: str | None = None
    published_at: str | None = None
    reason_discovered: str | None = None
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    raw_metadata: dict[str, Any] = field(default_factory=dict)
    point_in_time_safe: bool = True
    requires_live_validation: bool = True

    def to_dict(self) -> dict[str, Any]:
        headline = self.headline or self.title
        reason = self.reason_discovered or headline
        payload = {
            **asdict(self),
            "ticker": str(self.ticker or "").strip().upper(),
            "source": str(self.source or "external_catalyst").strip(),
            "source_type": "external_catalyst",
            "catalyst_type": str(self.catalyst_type or "unknown").strip().lower(),
            "title": str(self.title or headline or reason or "External catalyst candidate.").strip(),
            "headline": str(headline or self.title or reason or "").strip() or None,
            "reason_discovered": str(reason or "External catalyst candidate.").strip(),
            "discovered_at": self.discovered_at or utc_now_iso(),
            "as_of": self.as_of or self.published_at or self.discovered_at or utc_now_iso(),
            "published_at": self.published_at,
            "discovery_score": max(0.0, min(100.0, safe_float(self.discovery_score))),
            "confidence": max(0.0, min(1.0, safe_float(self.confidence, 0.5))),
            "reasons": unique_texts([reason, headline, self.title]),
            "warnings": unique_texts(self.warnings),
            "errors": unique_texts(self.errors),
            "raw_metadata": {
                **(self.raw_metadata or {}),
                "provider": self.source,
                "catalyst_type": str(self.catalyst_type or "unknown").strip().lower(),
                "external_discovery_score_only": True,
            },
            "point_in_time_safe": bool(self.point_in_time_safe),
            "requires_live_validation": True,
        }
        return payload
