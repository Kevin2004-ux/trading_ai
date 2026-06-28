from __future__ import annotations

from typing import Any

from scanner.universe_builder import validate_ticker_universe

from .catalyst_models import CATALYST_DISCOVERY_VERSION, CatalystDiscoveryRequest
from .catalyst_providers import CatalystProvider, configured_catalyst_providers
from .source_models import MAX_DISCOVERED_TICKERS, safe_float, unique_texts, utc_now_iso


def _bounded_max(value: int | None) -> int:
    try:
        numeric = int(value or 20)
    except (TypeError, ValueError):
        numeric = 20
    return max(1, min(numeric, MAX_DISCOVERED_TICKERS))


def _as_list(value: Any) -> list:
    return value if isinstance(value, list) else []


def _provider_names(statuses: list[dict[str, Any]], *, available_only: bool = False) -> list[str]:
    rows = []
    for status in statuses:
        if available_only and not status.get("available"):
            continue
        rows.append(status.get("provider_name"))
    return unique_texts(rows)


def discover_external_catalyst_candidates(
    *,
    max_tickers: int,
    discovered_at: str | None = None,
    intent_constraints: dict[str, Any] | None = None,
    seed_tickers: list[str] | None = None,
    providers: list[CatalystProvider] | None = None,
) -> dict[str, Any]:
    timestamp = discovered_at or utc_now_iso()
    max_count = _bounded_max(max_tickers)
    request = CatalystDiscoveryRequest(
        max_tickers=max_count,
        discovered_at=timestamp,
        intent_constraints=intent_constraints or {},
        seed_tickers=seed_tickers or [],
    )
    warnings: list[str] = []
    errors: list[str] = []
    provider_statuses: list[dict[str, Any]] = []
    candidates: list[dict[str, Any]] = []
    provider_rows = providers if providers is not None else configured_catalyst_providers()
    if not provider_rows:
        warnings.append("No external catalyst discovery providers are configured.")

    for provider in provider_rows:
        try:
            rows, status = provider.discover(request)
        except Exception as exc:
            status = provider.status()
            status.attempted = True
            status.errors.append(f"External catalyst provider failed: {exc}")
            rows = []
        status_payload = status.to_dict()
        provider_statuses.append(status_payload)
        warnings.extend(_as_list(status_payload.get("warnings")))
        errors.extend(_as_list(status_payload.get("errors")))
        candidates.extend(row for row in rows if isinstance(row, dict))

    validated_by_ticker: dict[str, dict[str, Any]] = {}
    if candidates:
        validation = validate_ticker_universe([str(row.get("ticker") or "") for row in candidates], max_tickers=max_count)
        valid_tickers = set(validation.get("tickers", []) if isinstance(validation, dict) else [])
        if isinstance(validation, dict):
            warnings.extend(str(item) for item in validation.get("errors", []) if item)
    else:
        valid_tickers = set()
    for row in candidates:
        ticker = str(row.get("ticker") or "").strip().upper()
        if ticker not in valid_tickers:
            continue
        normalized = dict(row)
        normalized["ticker"] = ticker
        normalized["source_type"] = "external_catalyst"
        normalized["requires_live_validation"] = True
        normalized["point_in_time_safe"] = bool(normalized.get("point_in_time_safe", True))
        normalized["discovery_score"] = safe_float(normalized.get("discovery_score"))
        existing = validated_by_ticker.get(ticker)
        if existing is None or safe_float(normalized.get("discovery_score")) > safe_float(existing.get("discovery_score")):
            validated_by_ticker[ticker] = normalized

    ranked = sorted(
        validated_by_ticker.values(),
        key=lambda row: (-safe_float(row.get("discovery_score")), str(row.get("ticker"))),
    )[:max_count]
    sources_used = unique_texts(row.get("source") for row in ranked)
    catalyst_types = unique_texts(row.get("catalyst_type") for row in ranked)

    return {
        "ok": True,
        "external_discovery_version": CATALYST_DISCOVERY_VERSION,
        "discovered_at": timestamp,
        "as_of": timestamp,
        "source_type": "external_catalyst",
        "sources_used": sources_used,
        "providers_attempted": _provider_names(provider_statuses),
        "providers_available": _provider_names(provider_statuses, available_only=True),
        "provider_statuses": provider_statuses,
        "catalyst_types": catalyst_types,
        "candidates": ranked,
        "tickers": [row["ticker"] for row in ranked],
        "discovered_count": len(ranked),
        "warnings": unique_texts(warnings),
        "errors": unique_texts(errors),
        "point_in_time_safe": all(bool(row.get("point_in_time_safe", True)) for row in ranked),
        "requires_live_validation": True,
        "external_discovery_used": bool(ranked),
    }
