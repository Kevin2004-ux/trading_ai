from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any

import config
from providers.market_data_provider import get_selected_market_data_provider
from providers.options_data_provider import get_selected_options_data_provider


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _as_dict(value: Any) -> dict:
    return value if isinstance(value, dict) else {}


def _as_list(value: Any) -> list:
    return value if isinstance(value, list) else []


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
class ProviderCapability:
    provider_name: str
    provider_type: str
    available: bool | None = None
    authenticated: bool | None = None
    entitlement_status: str = "unknown"
    supports_realtime_quotes: bool | None = None
    supports_historical_bars: bool | None = None
    supports_options_chain: bool | None = None
    supports_fundamentals: bool | None = None
    supports_news: bool | None = None
    supports_filings: bool | None = None
    supports_short_interest: bool | None = None
    rate_limited: bool = False
    degraded: bool = False
    last_checked_at: str | None = None
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        payload = asdict(self)
        payload["warnings"] = _unique_texts(self.warnings)
        payload["errors"] = _unique_texts(self.errors)
        return payload

    def compact(self) -> dict:
        return {
            "provider_name": self.provider_name,
            "provider_type": self.provider_type,
            "available": self.available,
            "authenticated": self.authenticated,
            "entitlement_status": self.entitlement_status,
            "supports_realtime_quotes": self.supports_realtime_quotes,
            "supports_historical_bars": self.supports_historical_bars,
            "supports_options_chain": self.supports_options_chain,
            "supports_fundamentals": self.supports_fundamentals,
            "supports_news": self.supports_news,
            "supports_filings": self.supports_filings,
            "supports_short_interest": self.supports_short_interest,
            "rate_limited": self.rate_limited,
            "degraded": self.degraded,
            "last_checked_at": self.last_checked_at,
            "warnings": _unique_texts(self.warnings),
            "errors": _unique_texts(self.errors),
        }


def _polygon_key_configured() -> bool:
    return bool(getattr(config, "POLYGON_API_KEY", None))


def configured_provider_capabilities() -> list[dict]:
    checked_at = _now_iso()
    market_provider = get_selected_market_data_provider()
    options_provider = get_selected_options_data_provider()
    rows: list[ProviderCapability] = []

    if market_provider == "polygon":
        authenticated = _polygon_key_configured()
        rows.append(
            ProviderCapability(
                provider_name="polygon",
                provider_type="market_data",
                available=authenticated,
                authenticated=authenticated,
                entitlement_status="configured" if authenticated else "missing_credentials",
                supports_realtime_quotes=True,
                supports_historical_bars=True,
                supports_options_chain=False,
                supports_fundamentals=False,
                supports_news=False,
                supports_filings=False,
                supports_short_interest=False,
                degraded=not authenticated,
                last_checked_at=checked_at,
                warnings=[] if authenticated else ["POLYGON_API_KEY is not configured."],
            )
        )
    else:
        rows.append(
            ProviderCapability(
                provider_name=market_provider,
                provider_type="market_data",
                available=None,
                authenticated=None,
                entitlement_status="configured_not_checked",
                supports_realtime_quotes=True,
                supports_historical_bars=True,
                supports_options_chain=False,
                degraded=True,
                last_checked_at=checked_at,
                warnings=["Provider capability was not live-checked; using runtime scan diagnostics when available."],
            )
        )

    if options_provider == "polygon":
        authenticated = _polygon_key_configured()
        rows.append(
            ProviderCapability(
                provider_name="polygon",
                provider_type="options_data",
                available=authenticated,
                authenticated=authenticated,
                entitlement_status="configured" if authenticated else "missing_credentials",
                supports_realtime_quotes=False,
                supports_historical_bars=False,
                supports_options_chain=True,
                supports_fundamentals=False,
                supports_news=False,
                supports_filings=False,
                supports_short_interest=False,
                degraded=not authenticated,
                last_checked_at=checked_at,
                warnings=[] if authenticated else ["POLYGON_API_KEY is not configured for options data."],
            )
        )
    else:
        rows.append(
            ProviderCapability(
                provider_name=options_provider,
                provider_type="options_data",
                available=None,
                authenticated=None,
                entitlement_status="configured_not_checked",
                supports_realtime_quotes=True,
                supports_historical_bars=False,
                supports_options_chain=True,
                degraded=True,
                last_checked_at=checked_at,
                warnings=["Options provider capability was not live-checked; using runtime option diagnostics when available."],
            )
        )

    return [row.compact() for row in rows]


def _walk_feature_provenance(payload: Any) -> list[dict]:
    rows: list[dict] = []
    if isinstance(payload, dict):
        feature_map = payload.get("feature_provenance")
        if isinstance(feature_map, dict):
            rows.extend(row for row in feature_map.values() if isinstance(row, dict))
        for value in payload.values():
            rows.extend(_walk_feature_provenance(value))
    elif isinstance(payload, list):
        for value in payload:
            rows.extend(_walk_feature_provenance(value))
    return rows


def _capability_from_provenance(provider: str, provider_type: str, rows: list[dict]) -> dict:
    warnings: list[str] = []
    errors: list[str] = []
    sources: set[str] = set()
    feature_names: set[str] = set()
    available = False
    recommendation_allowed = False
    checked_at = _now_iso()
    for row in rows:
        source = str(row.get("source") or "")
        feature = str(row.get("feature_name") or "")
        if source:
            sources.add(source)
        if feature:
            feature_names.add(feature)
        available = available or bool(row.get("feature_value_available"))
        recommendation_allowed = recommendation_allowed or bool(row.get("allowed_for_recommendation"))
        warnings.extend(str(item) for item in _as_list(row.get("warnings")) if item)
        errors.extend(str(item) for item in _as_list(row.get("errors")) if item)

    degraded = bool(errors or warnings or not recommendation_allowed)
    entitlement = "available" if recommendation_allowed and not degraded else "degraded" if available else "unavailable"
    return ProviderCapability(
        provider_name=provider,
        provider_type=provider_type,
        available=available,
        authenticated=None,
        entitlement_status=entitlement,
        supports_realtime_quotes=any("quote" in source for source in sources),
        supports_historical_bars=any("technical" in source or "historical" in source for source in sources),
        supports_options_chain=None,
        supports_fundamentals=False,
        supports_news=False,
        supports_filings=False,
        supports_short_interest=False,
        degraded=degraded,
        last_checked_at=checked_at,
        warnings=_unique_texts(warnings)[:8],
        errors=_unique_texts(errors)[:8],
    ).compact()


def summarize_provider_capabilities(payload: Any, *, fallback_to_configured: bool = True) -> list[dict]:
    provenance_rows = _walk_feature_provenance(payload)
    if not provenance_rows:
        return configured_provider_capabilities() if fallback_to_configured else []

    grouped: dict[tuple[str, str], list[dict]] = {}
    for row in provenance_rows:
        provider = str(row.get("provider") or "unknown")
        provider_type = str(row.get("provider_type") or "market_data")
        grouped.setdefault((provider, provider_type), []).append(row)

    capabilities = [
        _capability_from_provenance(provider, provider_type, rows)
        for (provider, provider_type), rows in sorted(grouped.items())
    ]
    configured = configured_provider_capabilities() if fallback_to_configured else []
    seen = {(row.get("provider_name"), row.get("provider_type")) for row in capabilities}
    capabilities.extend(
        row
        for row in configured
        if (row.get("provider_name"), row.get("provider_type")) not in seen
    )
    return capabilities
