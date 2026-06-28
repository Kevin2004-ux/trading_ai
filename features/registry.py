from __future__ import annotations

from .provenance import CORE_MARKET_FEATURES


FEATURE_REGISTRY = {
    "market_data": list(CORE_MARKET_FEATURES),
}


def registered_features(provider_type: str | None = None) -> list[str]:
    if provider_type:
        return list(FEATURE_REGISTRY.get(str(provider_type), []))
    features: list[str] = []
    for values in FEATURE_REGISTRY.values():
        features.extend(values)
    return list(dict.fromkeys(features))
