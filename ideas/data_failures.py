from __future__ import annotations

from typing import Any


DATA_FAILURE_CONSTRAINTS = {
    "scanner_error",
    "provider_error",
    "data_provider_error",
    "data_retrieval_error",
    "market_data_error",
    "market_data_unavailable",
    "historical_bars_unavailable",
    "quote_unavailable",
    "option_quotes_unavailable",
}

STRONG_PROVIDER_FAILURE_TEXT = (
    "connect call failed",
    "connectionrefusederror",
    "connection refused",
    "errno 61",
    "tws is not reachable",
    "tws/ibkr is not reachable",
    "ibkr/tws is not reachable",
    "ibkr historical bars unavailable",
    "historical bars unavailable",
    "market data could not be retrieved",
    "could not retrieve market data",
    "market data unavailable",
    "provider unavailable",
    "scanner_error",
)

WEAK_DATA_FAILURE_TEXT = (
    "quote unavailable",
    "quotes unavailable",
    "option chain unavailable",
    "option quotes unavailable",
    "empty api response",
    "empty response",
    "malformed ohlcv",
    "missing ohlcv",
    "no usable market data",
)


def _as_dict(value: Any) -> dict:
    return value if isinstance(value, dict) else {}


def _safe_float(value: Any) -> float | None:
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _string_values(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        rows: list[str] = []
        for nested in value.values():
            rows.extend(_string_values(nested))
        return rows
    if isinstance(value, list):
        rows: list[str] = []
        for nested in value:
            rows.extend(_string_values(nested))
        return rows
    return []


def normalized_text(value: Any) -> str:
    return " | ".join(_string_values(value)).lower()


def _has_positive_number(*values: Any) -> bool:
    for value in values:
        number = _safe_float(value)
        if number is not None and number > 0:
            return True
    return False


def has_usable_technical_snapshot(candidate: dict) -> bool:
    technical = _as_dict(candidate.get("technical_snapshot") or candidate.get("technical"))
    if not technical:
        return False
    useful_fields = (
        "current_price",
        "previous_close",
        "daily_return",
        "sma_20",
        "sma_50",
        "rsi_14",
        "average_volume_20",
        "relative_volume",
        "atr_14",
        "atr_percent",
    )
    return any(technical.get(field) not in (None, "", [], {}) for field in useful_fields)


def has_trade_prices(candidate: dict) -> bool:
    return _has_positive_number(
        candidate.get("current_price"),
        candidate.get("entry_price"),
        candidate.get("target_price"),
        candidate.get("stop_loss"),
        _as_dict(candidate.get("technical_snapshot")).get("current_price"),
    )


def has_option_quote_data(candidate: dict) -> bool:
    return _has_positive_number(
        candidate.get("bid"),
        candidate.get("ask"),
        candidate.get("mid"),
        candidate.get("last"),
        candidate.get("close"),
    )


def constraint_values(candidate: dict) -> set[str]:
    values: set[str] = set()
    for key in ("failed_constraints", "errors", "error_codes"):
        raw = candidate.get(key)
        if isinstance(raw, list):
            values.update(str(item).strip().lower() for item in raw if str(item).strip())
        elif isinstance(raw, str) and raw.strip():
            values.add(raw.strip().lower())

    constraint_results = _as_dict(candidate.get("constraint_results"))
    for key in ("failed_constraints", "errors"):
        raw = constraint_results.get(key)
        if isinstance(raw, list):
            values.update(str(item).strip().lower() for item in raw if str(item).strip())
        elif isinstance(raw, str) and raw.strip():
            values.add(raw.strip().lower())
    return values


def is_data_failure_candidate(candidate: dict) -> bool:
    if not isinstance(candidate, dict):
        return False

    data_quality = _as_dict(candidate.get("data_quality"))
    candidate_constraints = constraint_values(candidate)
    if candidate_constraints.intersection(DATA_FAILURE_CONSTRAINTS):
        return True

    quality_label = str(data_quality.get("quality_label") or "").strip().lower()
    if quality_label == "unavailable":
        return True

    text = normalized_text(
        {
            "candidate_errors": candidate.get("errors"),
            "candidate_error": candidate.get("error"),
            "rejection_reason": candidate.get("rejection_reason"),
            "reason": candidate.get("reason"),
            "data_quality": data_quality,
            "market_snapshot": candidate.get("market_snapshot"),
            "provider_status": candidate.get("provider_status"),
        }
    )
    if any(pattern in text for pattern in STRONG_PROVIDER_FAILURE_TEXT):
        return True

    has_price = has_trade_prices(candidate)
    has_technical = has_usable_technical_snapshot(candidate)
    has_option_quote = has_option_quote_data(candidate)
    has_weak_provider_text = any(pattern in text for pattern in WEAK_DATA_FAILURE_TEXT)

    if data_quality.get("ok") is False and has_weak_provider_text:
        return True
    if has_weak_provider_text and not (has_price or has_technical or has_option_quote):
        return True
    return False


def candidate_failure_issues(candidate: dict) -> tuple[list[str], list[str]]:
    data_missing: list[str] = []
    system_issues: list[str] = []
    text = normalized_text(candidate)
    data_quality = _as_dict(candidate.get("data_quality"))

    if any(pattern in text for pattern in ("connect call failed", "connectionrefusederror", "connection refused", "errno 61", "tws is not reachable", "ibkr/tws is not reachable")):
        system_issues.append("IBKR/TWS is not reachable on 127.0.0.1:7496. Live market data is unavailable.")
    if "historical bars unavailable" in text:
        data_missing.append("Historical bars are unavailable from the configured market-data provider.")
    if "quote unavailable" in text or "quotes unavailable" in text:
        data_missing.append("Live quote data is unavailable from the configured market-data provider.")
    if "option chain unavailable" in text or "option quotes unavailable" in text:
        data_missing.append("Option chain/quote data is unavailable from the configured options provider.")
    if data_quality.get("quality_label") == "unavailable" or "scanner_error" in constraint_values(candidate):
        data_missing.append("Scanner/provider failures returned no usable market data for one or more candidates.")
    if not data_missing and not system_issues:
        data_missing.append("Usable market data was not returned for one or more candidates.")
    return data_missing, system_issues


def split_data_failures(candidates: list[dict]) -> tuple[list[dict], list[dict]]:
    usable: list[dict] = []
    failures: list[dict] = []
    for candidate in candidates:
        if is_data_failure_candidate(candidate):
            failures.append(candidate)
        else:
            usable.append(candidate)
    return usable, failures


def extend_issues_from_failures(data_missing: list[str], system_issues: list[str], failures: list[dict]) -> None:
    for failure in failures:
        missing, issues = candidate_failure_issues(failure)
        data_missing.extend(missing)
        system_issues.extend(issues)
