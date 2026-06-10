from __future__ import annotations

from datetime import datetime, timezone
import re


_TICKER_PATTERN = re.compile(r"^[A-Z][A-Z0-9.\-]{0,9}$")

_CURATED_UNIVERSES = {
    "mega_cap": [
        "AAPL", "MSFT", "NVDA", "AMZN", "GOOGL", "GOOG", "META", "BRK.B", "LLY", "AVGO",
        "TSM", "JPM", "V", "WMT", "XOM", "UNH", "MA", "COST", "JNJ", "PG",
    ],
    "large_cap": [
        "AAPL", "MSFT", "NVDA", "AMZN", "GOOGL", "META", "TSLA", "AMD", "NFLX", "COST",
        "JPM", "BAC", "GS", "V", "MA", "WMT", "HD", "LOW", "UNH", "LLY",
        "XOM", "CVX", "CAT", "DE", "GE", "LIN", "ADBE", "CRM", "ORCL", "NOW",
        "UBER", "SHOP", "PANW", "CRWD", "SNOW", "MELI", "PDD", "TTD", "ARM", "ANET",
    ],
    "active": [
        "TSLA", "NVDA", "AAPL", "AMD", "AMZN", "META", "PLTR", "SOFI", "RIVN", "CCL",
        "NIO", "MARA", "RIOT", "GME", "LCID", "T", "F", "INTC", "BAC", "AAL",
        "UAL", "DAL", "PFE", "CVNA", "SNAP", "HOOD", "COIN", "UPST", "SMCI", "HIMS",
    ],
    "tech": [
        "AAPL", "MSFT", "NVDA", "AMD", "AVGO", "ORCL", "ADBE", "CRM", "NOW", "PANW",
        "CRWD", "SNOW", "ANET", "MU", "INTC", "QCOM", "TXN", "AMAT", "KLAC", "LRCX",
        "SHOP", "NET", "DDOG", "MDB", "ZS", "TEAM", "DOCU", "PLTR", "SMCI", "ARM",
    ],
    "growth": [
        "NVDA", "AMD", "AMZN", "META", "NFLX", "SHOP", "SNOW", "PLTR", "CRWD", "PANW",
        "TTD", "MELI", "UBER", "HIMS", "CAVA", "CELH", "DUOL", "NET", "DDOG", "APP",
        "TOST", "AXON", "PINS", "COIN", "HOOD", "SMCI", "ARM", "PDD", "RKLB", "NU",
    ],
    "sp500_sample": [
        "AAPL", "MSFT", "NVDA", "AMZN", "GOOGL", "META", "JPM", "XOM", "UNH", "PG",
        "JNJ", "COST", "HD", "BAC", "ABBV", "KO", "PEP", "MRK", "CVX", "WMT",
        "LLY", "V", "MA", "DIS", "MCD", "CAT", "GE", "ADBE", "CRM", "ORCL",
    ],
}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _response(
    ok: bool,
    universe: str,
    tickers: list[str] | None,
    source: str,
    max_tickers: int,
    errors: list[str] | None = None,
) -> dict:
    ticker_list = tickers or []
    return {
        "ok": ok,
        "universe": universe,
        "timestamp": _now_iso(),
        "tickers": ticker_list,
        "count": len(ticker_list),
        "source": source,
        "max_tickers": max_tickers,
        "errors": errors or [],
    }


def validate_ticker_universe(
    tickers: list[str],
    max_tickers: int = 500,
) -> dict:
    errors: list[str] = []
    if not isinstance(tickers, list):
        return _response(False, "custom", [], "custom", max_tickers, ["Ticker universe must be provided as a list."])

    seen: set[str] = set()
    normalized: list[str] = []

    for raw_ticker in tickers:
        ticker = str(raw_ticker or "").strip().upper()
        if not ticker:
            errors.append("Ignored empty ticker symbol.")
            continue
        if not _TICKER_PATTERN.match(ticker):
            errors.append(f"Ignored invalid ticker symbol: {ticker}")
            continue
        if ticker in seen:
            continue
        seen.add(ticker)
        normalized.append(ticker)

    if len(normalized) > max_tickers:
        normalized = normalized[:max_tickers]
        errors.append(f"Ticker universe exceeded max_tickers={max_tickers} and was truncated.")

    ok = len(normalized) > 0
    if not ok and not errors:
        errors.append("No valid tickers were provided.")
    return _response(ok, "custom", normalized, "custom", max_tickers, errors)


def build_custom_universe(
    tickers: list[str],
    max_tickers: int = 500,
) -> dict:
    validated = validate_ticker_universe(tickers, max_tickers=max_tickers)
    validated["universe"] = "custom"
    validated["source"] = "custom"
    return validated


def get_default_universe(
    universe: str = "large_cap",
    max_tickers: int = 500,
) -> dict:
    normalized_universe = str(universe or "").strip().lower()
    if normalized_universe == "custom":
        return _response(False, normalized_universe, [], "custom", max_tickers, ["Use build_custom_universe(...) for custom ticker lists."])

    tickers = _CURATED_UNIVERSES.get(normalized_universe)
    if tickers is None:
        return _response(
            False,
            normalized_universe,
            [],
            "static_curated",
            max_tickers,
            [
                f"Unknown universe: {universe}",
                f"Supported universes: {', '.join(sorted(list(_CURATED_UNIVERSES.keys()) + ['custom']))}",
            ],
        )

    validated = validate_ticker_universe(tickers, max_tickers=max_tickers)
    validated["universe"] = normalized_universe
    validated["source"] = "static_curated"
    return validated
