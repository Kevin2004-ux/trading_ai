from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


def _json_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _json_safe(nested) for key, nested in value.items()}
    if isinstance(value, list):
        return [_json_safe(item) for item in value]
    if isinstance(value, tuple):
        return [_json_safe(item) for item in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def _unique_texts(values: list[Any] | None) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values or []:
        text = str(value or "").strip()
        if not text:
            continue
        key = text.lower()
        if key in seen:
            continue
        seen.add(key)
        result.append(text)
    return result


@dataclass
class FeatureProvenance:
    feature_name: str
    feature_value_available: bool
    provider: str = "unknown"
    provider_type: str = "market_data"
    source: str = "unknown"
    as_of: str | None = None
    observed_at: str | None = None
    freshness_seconds: float | None = None
    freshness_label: str | None = None
    confidence: str = "unknown"
    point_in_time_safe: bool = True
    requires_live_validation: bool = False
    allowed_for_recommendation: bool = False
    allowed_for_research_only: bool = False
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    raw_metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        payload = asdict(self)
        payload["warnings"] = _unique_texts(self.warnings)
        payload["errors"] = _unique_texts(self.errors)
        payload["raw_metadata"] = _json_safe(self.raw_metadata)
        return payload

    def compact(self) -> dict:
        return {
            "feature_name": self.feature_name,
            "available": self.feature_value_available,
            "provider": self.provider,
            "provider_type": self.provider_type,
            "source": self.source,
            "as_of": self.as_of,
            "freshness_label": self.freshness_label,
            "confidence": self.confidence,
            "point_in_time_safe": self.point_in_time_safe,
            "requires_live_validation": self.requires_live_validation,
            "allowed_for_recommendation": self.allowed_for_recommendation,
            "allowed_for_research_only": self.allowed_for_research_only,
            "warnings": _unique_texts(self.warnings),
            "errors": _unique_texts(self.errors),
        }
