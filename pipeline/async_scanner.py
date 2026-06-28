from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import inspect
import os
import time
from typing import Any, Callable

from pipeline.rate_limiter import AsyncRateLimiter
from pipeline.scan_state import ScanState


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, default))
    except (TypeError, ValueError):
        return default


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, default))
    except (TypeError, ValueError):
        return default


def _merge_config(config: dict | None = None) -> dict:
    merged = {
        "max_concurrency": _env_int("SCAN_MAX_CONCURRENCY", 5),
        "ticker_timeout_seconds": _env_float("SCAN_TICKER_TIMEOUT_SECONDS", 15.0),
        "total_timeout_seconds": _env_float("SCAN_TOTAL_TIMEOUT_SECONDS", 180.0),
        "provider_bucket": "ibkr_market_data",
        "rate_limiter": None,
    }
    if isinstance(config, dict):
        merged.update(config)
    merged["max_concurrency"] = max(1, int(merged["max_concurrency"]))
    merged["ticker_timeout_seconds"] = max(0.01, float(merged["ticker_timeout_seconds"]))
    merged["total_timeout_seconds"] = max(0.01, float(merged["total_timeout_seconds"]))
    return merged


async def _call_scan_fn(scan_fn: Callable, ticker: str, executor: ThreadPoolExecutor | None = None) -> Any:
    if inspect.iscoroutinefunction(scan_fn):
        return await scan_fn(ticker)
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(executor, scan_fn, ticker)


async def async_scan_tickers(
    tickers: list[str],
    scan_fn,
    config: dict | None = None,
) -> dict:
    cfg = _merge_config(config)
    started = time.monotonic()
    timestamp = _now_iso()
    normalized_tickers = [str(ticker).strip().upper() for ticker in tickers or [] if str(ticker).strip()]
    state = ScanState(normalized_tickers)
    results: list[dict] = []
    semaphore = asyncio.Semaphore(cfg["max_concurrency"])
    rate_limiter = cfg.get("rate_limiter") or AsyncRateLimiter()
    provider_bucket = str(cfg.get("provider_bucket") or "ibkr_market_data")

    if not normalized_tickers:
        state.add_warning("No valid tickers were provided.")
        state.complete()
        return {
            "ok": False,
            "completed": True,
            "timestamp": timestamp,
            "total_tickers": 0,
            "completed_tickers": 0,
            "failed_tickers": [],
            "timed_out_tickers": [],
            "results": [],
            "errors": state.errors,
            "warnings": state.warnings,
            "duration_seconds": round(time.monotonic() - started, 4),
            "state": state.summary(),
        }

    executor = None if inspect.iscoroutinefunction(scan_fn) else ThreadPoolExecutor(
        max_workers=cfg["max_concurrency"],
        thread_name_prefix="async-scanner",
    )

    async def worker(ticker: str) -> dict:
        async with semaphore:
            state.mark_started(ticker)
            try:
                async with rate_limiter.limit(provider_bucket):
                    payload = await asyncio.wait_for(
                        _call_scan_fn(scan_fn, ticker, executor),
                        timeout=cfg["ticker_timeout_seconds"],
                    )
                state.mark_completed(ticker)
                return {"ok": True, "ticker": ticker, "result": payload}
            except asyncio.TimeoutError:
                message = f"{ticker} timed out after {cfg['ticker_timeout_seconds']} seconds."
                state.mark_timed_out(ticker, message)
                return {"ok": False, "ticker": ticker, "error_type": "timeout", "error": message}
            except asyncio.CancelledError:
                message = f"{ticker} was cancelled because the total scan timeout was reached."
                state.mark_timed_out(ticker, message)
                return {"ok": False, "ticker": ticker, "error_type": "timeout", "error": message}
            except Exception as exc:
                message = f"{ticker} scan failed: {exc}"
                state.mark_failed(ticker, message)
                return {"ok": False, "ticker": ticker, "error_type": "exception", "error": message}

    tasks = {asyncio.create_task(worker(ticker)): ticker for ticker in normalized_tickers}
    done, pending = await asyncio.wait(tasks.keys(), timeout=cfg["total_timeout_seconds"])

    for task in done:
        try:
            result = task.result()
        except Exception as exc:
            ticker = tasks.get(task, "UNKNOWN")
            message = f"{ticker} scan failed unexpectedly: {exc}"
            state.mark_failed(ticker, message)
            result = {"ok": False, "ticker": ticker, "error_type": "exception", "error": message}
        results.append(result)

    if pending:
        warning = "Scan completed with partial results due to timeout or provider failures."
        state.add_warning(warning)
        for task in pending:
            ticker = tasks.get(task, "UNKNOWN")
            task.cancel()
            message = f"{ticker} was not completed before the total scan timeout of {cfg['total_timeout_seconds']} seconds."
            state.mark_timed_out(ticker, message)
            results.append({"ok": False, "ticker": ticker, "error_type": "timeout", "error": message})
        await asyncio.gather(*pending, return_exceptions=True)

    state.complete()
    timed_out = sorted(state.timed_out_tickers)
    failed = sorted(state.failed_tickers)
    completed_count = len(state.completed_tickers)
    completed = not pending and not timed_out and not failed
    warnings = list(state.warnings)
    if (timed_out or failed) and "Scan completed with partial results due to timeout or provider failures." not in warnings:
        warnings.append("Scan completed with partial results due to timeout or provider failures.")

    response = {
        "ok": completed_count > 0,
        "completed": completed,
        "timestamp": timestamp,
        "total_tickers": len(normalized_tickers),
        "completed_tickers": completed_count,
        "failed_tickers": failed,
        "timed_out_tickers": timed_out,
        "results": results,
        "errors": list(state.errors),
        "warnings": warnings,
        "duration_seconds": round(time.monotonic() - started, 4),
        "state": state.summary(),
    }
    if executor is not None:
        executor.shutdown(wait=False, cancel_futures=True)
    return response


def run_async_scan_tickers(
    tickers: list[str],
    scan_fn,
    config: dict | None = None,
) -> dict:
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(async_scan_tickers(tickers, scan_fn, config=config))
    raise RuntimeError("run_async_scan_tickers cannot be called from an active event loop.")
