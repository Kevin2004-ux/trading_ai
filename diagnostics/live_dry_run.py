from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any, Callable

import config
from memory.vector_memory import find_similar_setups, get_memory_config
from providers.market_data_provider import get_selected_market_data_provider
from providers.options_data_provider import get_selected_options_data_provider
from realtime.catalyst_enrichment import get_news_snapshot
from realtime.market_data import get_market_snapshot
from realtime.options_chain import get_options_chain
from research.earnings_transcripts import get_earnings_transcript_snapshot
from research.sec_filings import get_sec_filing_snapshot


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _env_or_config(name: str) -> str | None:
    return os.getenv(name) or getattr(config, name, None)


def _skipped(provider: str, reason: str) -> dict:
    return {
        "ok": False,
        "provider": provider,
        "status": "unavailable",
        "usable": False,
        "data": None,
        "error": reason,
    }


def _provider_call(provider: str, fn: Callable[[], dict]) -> dict:
    try:
        result = fn()
        ok = bool(result.get("ok")) if isinstance(result, dict) else False
        status = "usable" if ok else "unavailable"
        return {
            "ok": ok,
            "provider": provider,
            "status": status,
            "usable": ok,
            "data": result,
            "error": None if ok else (result.get("error", "Provider returned an unavailable response.") if isinstance(result, dict) else "Provider returned malformed data."),
        }
    except Exception as exc:
        return {
            "ok": False,
            "provider": provider,
            "status": "failed",
            "usable": False,
            "data": None,
            "error": str(exc),
        }


def run_provider_dry_run(
    ticker: str = "AAPL",
    include_market_data: bool = True,
    include_news: bool = True,
    include_sec_filings: bool = True,
    include_earnings_transcripts: bool = True,
    include_options: bool = True,
    include_memory: bool = False,
    db_path: str = "strategy_library.db",
) -> dict:
    normalized_ticker = str(ticker or "AAPL").strip().upper() or "AAPL"
    checks: dict[str, dict] = {}
    warnings: list[str] = [
        "Live provider dry run only. No trades are placed and no final recommendations are logged.",
        "Provider calls may use live API quotas when keys are configured.",
    ]
    errors: list[str] = []

    polygon_missing = not _env_or_config("POLYGON_API_KEY")
    fmp_missing = not _env_or_config("FMP_API_KEY")
    market_provider = get_selected_market_data_provider()
    options_provider = get_selected_options_data_provider()

    if market_provider == "ibkr" or options_provider == "ibkr":
        from providers.ibkr_provider import check_ibkr_connection

        checks["ibkr_connection"] = _provider_call("ibkr", check_ibkr_connection)

    if include_market_data:
        if market_provider == "ibkr":
            checks["market_data"] = _provider_call("ibkr", lambda: get_market_snapshot(normalized_ticker))
        elif polygon_missing:
            checks["market_data"] = _skipped("polygon", "POLYGON_API_KEY is not configured.")
        else:
            checks["market_data"] = _provider_call("polygon", lambda: get_market_snapshot(normalized_ticker))
    else:
        checks["market_data"] = _skipped(market_provider, "Market data check was disabled.")

    if include_news:
        if fmp_missing:
            checks["news"] = _skipped("fmp", "FMP_API_KEY is not configured.")
        else:
            checks["news"] = _provider_call("fmp", lambda: get_news_snapshot(normalized_ticker))
    else:
        checks["news"] = _skipped("fmp", "News check was disabled.")

    if include_sec_filings:
        if fmp_missing:
            checks["sec_filings"] = _skipped("fmp", "FMP_API_KEY is not configured.")
        else:
            checks["sec_filings"] = _provider_call("fmp", lambda: get_sec_filing_snapshot(normalized_ticker))
    else:
        checks["sec_filings"] = _skipped("fmp", "SEC filings check was disabled.")

    if include_earnings_transcripts:
        if fmp_missing:
            checks["earnings_transcripts"] = _skipped("fmp", "FMP_API_KEY is not configured.")
        else:
            checks["earnings_transcripts"] = _provider_call("fmp", lambda: get_earnings_transcript_snapshot(normalized_ticker))
    else:
        checks["earnings_transcripts"] = _skipped("fmp", "Earnings transcripts check was disabled.")

    if include_options:
        if options_provider == "ibkr":
            checks["options"] = _provider_call("ibkr_options", lambda: get_options_chain(normalized_ticker))
        elif polygon_missing:
            checks["options"] = _skipped("polygon_options", "POLYGON_API_KEY is not configured.")
        else:
            checks["options"] = _provider_call("polygon_options", lambda: get_options_chain(normalized_ticker))
    else:
        checks["options"] = _skipped(options_provider, "Options check was disabled.")

    if include_memory:
        memory_config = get_memory_config()
        if not memory_config.get("pinecone_configured"):
            checks["memory"] = _skipped("pinecone", "Pinecone memory is not configured.")
        else:
            checks["memory"] = _provider_call("pinecone", lambda: find_similar_setups({"ticker": normalized_ticker}, top_k=3))
    else:
        checks["memory"] = _skipped("pinecone", "Memory check was disabled.")

    for name, check in checks.items():
        if check.get("status") == "unavailable":
            warnings.append(f"{name} unavailable: {check.get('error')}")
        elif check.get("status") == "failed":
            errors.append(f"{name} failed: {check.get('error')}")

    return {
        "ok": not errors,
        "timestamp": _now_iso(),
        "ticker": normalized_ticker,
        "db_path": db_path,
        "selected_providers": {
            "market_data_provider": market_provider,
            "options_data_provider": options_provider,
        },
        "checks": checks,
        "warnings": warnings,
        "errors": errors,
    }
