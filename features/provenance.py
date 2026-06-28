from __future__ import annotations

from typing import Any

from .models import FeatureProvenance


CORE_MARKET_FEATURES = (
    "current_price",
    "volume",
    "average_volume_20",
    "relative_volume",
    "sma_20",
    "sma_50",
    "sma_200",
)


def _as_dict(value: Any) -> dict:
    return value if isinstance(value, dict) else {}


def _as_list(value: Any) -> list:
    return value if isinstance(value, list) else []


def _safe_float(value: Any) -> float | None:
    try:
        if value in (None, ""):
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


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


def _feature_value(data: dict, technical: dict, quote: dict, feature_name: str) -> Any:
    if feature_name == "current_price":
        return quote.get("last_price") if quote.get("last_price") not in (None, "") else technical.get("current_price")
    if feature_name == "volume":
        return quote.get("day_volume")
    return technical.get(feature_name)


def _feature_source(quote: dict, feature_name: str) -> str:
    if feature_name == "current_price" and quote.get("last_price") not in (None, ""):
        return "quote.last_price"
    if feature_name == "volume":
        return "quote.day_volume"
    return "technical_snapshot"


def _feature_as_of(freshness: dict, quote: dict, feature_name: str) -> str | None:
    if feature_name in {"current_price", "volume"} and quote.get("last_trade_timestamp"):
        return str(quote.get("last_trade_timestamp"))
    return freshness.get("latest_bar_timestamp")


def _confidence(*, available: bool, allowed_base: bool, point_in_time_safe: bool, freshness: dict) -> str:
    if not available:
        return "none"
    if not point_in_time_safe:
        return "low"
    if allowed_base and freshness.get("freshness_label") in {"fresh", "latest_completed_session"}:
        return "high"
    if allowed_base:
        return "medium"
    return "low"


def build_core_market_feature_provenance(
    ticker: str,
    market_snapshot: dict | None,
    *,
    data_quality: dict | None = None,
) -> dict[str, dict]:
    snapshot = _as_dict(market_snapshot)
    data = _as_dict(snapshot.get("data"))
    technical = _as_dict(data.get("technical_snapshot"))
    quote = _as_dict(data.get("quote"))
    freshness = _as_dict(data.get("data_freshness"))
    quality = _as_dict(data_quality or data.get("data_quality"))
    provider = str(quality.get("price_source") or snapshot.get("source") or "unknown")
    observed_at = snapshot.get("timestamp")
    freshness_label = freshness.get("freshness_label")
    point_in_time_safe = not bool(freshness.get("is_stale"))
    allowed_base = bool(quality.get("final_recommendation_allowed", snapshot.get("ok") is True))
    base_warnings = _unique_texts(
        [
            *list(_as_list(quality.get("warnings"))),
            *list(_as_list(freshness.get("warnings"))),
        ]
    )
    base_errors = _unique_texts(
        [
            *list(_as_list(quality.get("errors"))),
            *([snapshot.get("error")] if snapshot.get("error") else []),
            *([technical.get("error")] if technical.get("error") else []),
        ]
    )

    provenance: dict[str, dict] = {}
    for feature_name in CORE_MARKET_FEATURES:
        value = _feature_value(data, technical, quote, feature_name)
        available = value not in (None, "", [], {})
        warnings = list(base_warnings)
        errors = list(base_errors)
        if not available:
            warnings.append(f"{feature_name} is missing or unavailable.")
        if not point_in_time_safe:
            warnings.append(f"{feature_name} is not point-in-time safe because market data is stale.")
        allowed_for_recommendation = bool(available and allowed_base and point_in_time_safe)
        provenance[feature_name] = FeatureProvenance(
            feature_name=feature_name,
            feature_value_available=available,
            provider=provider,
            provider_type="market_data",
            source=_feature_source(quote, feature_name),
            as_of=_feature_as_of(freshness, quote, feature_name),
            observed_at=str(observed_at) if observed_at else None,
            freshness_seconds=None,
            freshness_label=str(freshness_label) if freshness_label else None,
            confidence=_confidence(
                available=available,
                allowed_base=allowed_base,
                point_in_time_safe=point_in_time_safe,
                freshness=freshness,
            ),
            point_in_time_safe=point_in_time_safe,
            requires_live_validation=False,
            allowed_for_recommendation=allowed_for_recommendation,
            allowed_for_research_only=bool(available),
            warnings=warnings,
            errors=errors,
            raw_metadata={
                "ticker": str(ticker or snapshot.get("ticker") or "").upper(),
                "quote_status": data.get("quote_status") or quality.get("quote_status"),
                "quality_label": quality.get("quality_label"),
                "latest_bar_timestamp": freshness.get("latest_bar_timestamp"),
                "age_days": _safe_float(freshness.get("age_days")),
            },
        ).to_dict()
    return provenance


def summarize_feature_provenance(feature_provenance: dict | None) -> dict:
    rows = [_as_dict(row) for row in _as_dict(feature_provenance).values()]
    if not rows:
        return {
            "feature_count": 0,
            "available_count": 0,
            "allowed_for_recommendation_count": 0,
            "unsafe_features": [],
            "providers": [],
            "warnings": [],
            "errors": [],
        }
    unsafe = [
        str(row.get("feature_name"))
        for row in rows
        if not bool(row.get("allowed_for_recommendation"))
    ]
    providers = sorted({str(row.get("provider") or "unknown") for row in rows})
    warnings: list[str] = []
    errors: list[str] = []
    for row in rows:
        warnings.extend(str(item) for item in _as_list(row.get("warnings")) if item)
        errors.extend(str(item) for item in _as_list(row.get("errors")) if item)
    return {
        "feature_count": len(rows),
        "available_count": sum(1 for row in rows if row.get("feature_value_available")),
        "allowed_for_recommendation_count": sum(1 for row in rows if row.get("allowed_for_recommendation")),
        "unsafe_features": unsafe,
        "providers": providers,
        "warnings": _unique_texts(warnings)[:8],
        "errors": _unique_texts(errors)[:8],
    }


def provenance_warning_messages(feature_provenance: dict | None) -> list[str]:
    summary = summarize_feature_provenance(feature_provenance)
    unsafe = summary.get("unsafe_features", [])
    if not unsafe:
        return []
    return [
        "Feature provenance is incomplete or not allowed for final recommendation use: "
        + ", ".join(str(item) for item in unsafe[:8])
    ]
