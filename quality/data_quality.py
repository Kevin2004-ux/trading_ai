from __future__ import annotations

from typing import Any

import config


QUALITY_GOOD = "good"
QUALITY_USABLE_WITH_WARNINGS = "usable_with_warnings"
QUALITY_POOR = "poor"
QUALITY_UNAVAILABLE = "unavailable"


def _bool_setting(name: str, default: bool = False) -> bool:
    value = getattr(config, name, None)
    if value is None:
        value = default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def _safe_float(value: Any) -> float | None:
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def validate_market_data_quality(
    market_snapshot: dict,
    max_stale_days: int = 3,
) -> dict:
    warnings: list[str] = []
    errors: list[str] = []
    if not isinstance(market_snapshot, dict) or not market_snapshot.get("ok"):
        return {
            "ok": False,
            "quality_label": QUALITY_UNAVAILABLE,
            "price_source": None,
            "quote_status": "unavailable",
            "final_recommendation_allowed": False,
            "warnings": [],
            "errors": [market_snapshot.get("error", "Market data provider failed.") if isinstance(market_snapshot, dict) else "Market snapshot is missing."],
        }

    data = market_snapshot.get("data") if isinstance(market_snapshot.get("data"), dict) else {}
    quote = data.get("quote") if isinstance(data.get("quote"), dict) else {}
    freshness = data.get("data_freshness") if isinstance(data.get("data_freshness"), dict) else {}
    technical = data.get("technical_snapshot") if isinstance(data.get("technical_snapshot"), dict) else {}

    price = _safe_float(quote.get("last_price")) or _safe_float(technical.get("current_price"))
    price_source = quote.get("quote_source") or ("technical_snapshot" if price is not None else None)
    quote_status = "available" if quote and quote.get("quote_source") != "historical_bar_fallback" else "unavailable"
    fallback_used = bool(data.get("quote_fallback_used")) or price_source == "historical_bar_fallback"

    if fallback_used:
        price_source = "historical_bar_fallback"
        quote_status = "unavailable"
        warnings.append("IBKR live quote unavailable; using latest historical close.")
        warnings.append("Not suitable for intraday entry decisions.")

    warnings.extend(str(item) for item in data.get("data_quality_warnings", []) if item)

    age_days = _safe_float(freshness.get("age_days"))
    freshness_label = str(freshness.get("freshness_label", "")).lower()
    session_status = freshness.get("market_session") if isinstance(freshness.get("market_session"), dict) else {}
    usable_freshness_labels = {"fresh", "latest_completed_session", "slightly_stale"}
    is_stale = bool(freshness.get("is_stale"))

    if session_status.get("is_stale_by_session") is True:
        is_stale = True
    elif freshness.get("is_stale") is False and freshness_label in usable_freshness_labels:
        is_stale = False
    elif age_days is not None and age_days > max_stale_days:
        is_stale = True

    if freshness_label == "latest_completed_session" and age_days is not None and age_days > max_stale_days:
        warnings.append("Latest historical bar matches the latest completed market session despite a weekend/holiday gap.")
    warnings.extend(str(item) for item in freshness.get("warnings", []) if item)
    if is_stale:
        errors.append("Latest historical bar is stale.")

    if price is None:
        errors.append("Critical price data is missing.")

    if errors:
        quality_label = QUALITY_POOR if price is not None else QUALITY_UNAVAILABLE
        final_allowed = False
    elif fallback_used:
        quality_label = QUALITY_USABLE_WITH_WARNINGS
        final_allowed = _bool_setting("ALLOW_HISTORICAL_BAR_FALLBACK", True) and not _bool_setting("ALLOW_LIVE_QUOTE_REQUIRED", False)
        if not final_allowed:
            errors.append("Historical-bar fallback is not allowed for final recommendations.")
    else:
        quality_label = QUALITY_GOOD
        final_allowed = True

    return {
        "ok": quality_label in {QUALITY_GOOD, QUALITY_USABLE_WITH_WARNINGS} and not errors,
        "quality_label": quality_label,
        "price_source": price_source,
        "quote_status": quote_status,
        "final_recommendation_allowed": final_allowed,
        "warnings": warnings,
        "errors": errors,
    }


def validate_options_chain_quality(
    options_chain: list[dict] | dict,
    max_stale_days: int = 3,
) -> dict:
    del max_stale_days
    rows = options_chain
    if isinstance(options_chain, dict):
        if not options_chain.get("ok"):
            summary = ((options_chain.get("data") or {}).get("diagnostic") or {}).get("permissions_summary", {})
            errors = [options_chain.get("error", "Options chain unavailable.")]
            if summary.get("likely_missing_opra") or not summary.get("option_quotes_available", False):
                errors.append("Options quotes unavailable; OPRA/options quote data required before final options recommendations.")
            return {
                "ok": False,
                "quality_label": QUALITY_UNAVAILABLE,
                "final_recommendation_allowed": False,
                "warnings": [],
                "errors": errors,
            }
        rows = (options_chain.get("data") or {}).get("contracts", [])

    if not isinstance(rows, list) or not rows:
        return {
            "ok": False,
            "quality_label": QUALITY_UNAVAILABLE,
            "final_recommendation_allowed": False,
            "warnings": [],
            "errors": ["Options quotes unavailable; OPRA/options quote data required before final options recommendations."],
        }

    usable = [
        row for row in rows
        if isinstance(row, dict)
        and _safe_float(row.get("bid")) is not None
        and _safe_float(row.get("ask")) is not None
        and _safe_float(row.get("mid")) is not None
    ]
    if not usable:
        return {
            "ok": False,
            "quality_label": QUALITY_POOR,
            "final_recommendation_allowed": False,
            "warnings": [],
            "errors": ["No option contracts have usable bid/ask/mid quotes."],
        }

    return {
        "ok": True,
        "quality_label": QUALITY_GOOD,
        "final_recommendation_allowed": not _bool_setting("ALLOW_OPTIONS_WITHOUT_QUOTES", False) or bool(usable),
        "warnings": [],
        "errors": [],
    }


def validate_tool_response_quality(tool_response: dict) -> dict:
    if not isinstance(tool_response, dict):
        return {
            "ok": False,
            "quality_label": QUALITY_UNAVAILABLE,
            "warnings": [],
            "errors": ["Tool response is missing or malformed."],
        }
    if not tool_response.get("ok"):
        return {
            "ok": False,
            "quality_label": QUALITY_UNAVAILABLE,
            "warnings": [],
            "errors": [tool_response.get("error", "Tool returned an unavailable response.")],
        }
    return {
        "ok": True,
        "quality_label": QUALITY_GOOD,
        "warnings": [],
        "errors": [],
    }


def build_data_quality_summary(
    quality_results: list[dict],
) -> dict:
    labels = [item.get("quality_label", QUALITY_UNAVAILABLE) for item in quality_results if isinstance(item, dict)]
    warnings = list(dict.fromkeys(
        warning
        for item in quality_results
        if isinstance(item, dict)
        for warning in item.get("warnings", [])
        if warning
    ))
    errors = list(dict.fromkeys(
        error
        for item in quality_results
        if isinstance(item, dict)
        for error in item.get("errors", [])
        if error
    ))
    counts = {label: labels.count(label) for label in [QUALITY_GOOD, QUALITY_USABLE_WITH_WARNINGS, QUALITY_POOR, QUALITY_UNAVAILABLE]}
    return {
        "ok": not errors,
        "total": len(quality_results),
        "counts": counts,
        "warnings": warnings,
        "errors": errors,
        "worst_quality_label": (
            QUALITY_UNAVAILABLE if counts[QUALITY_UNAVAILABLE]
            else QUALITY_POOR if counts[QUALITY_POOR]
            else QUALITY_USABLE_WITH_WARNINGS if counts[QUALITY_USABLE_WITH_WARNINGS]
            else QUALITY_GOOD if quality_results
            else QUALITY_UNAVAILABLE
        ),
    }
