import asyncio

from pipeline.async_scanner import async_scan_tickers
from pipeline.rate_limiter import AsyncRateLimiter


def _fast_limiter() -> AsyncRateLimiter:
    return AsyncRateLimiter(
        {
            "test_provider": {
                "max_calls_per_second": 1000,
                "max_concurrent_calls": 20,
            }
        }
    )


def test_async_scanner_completes_all_tickers_successfully():
    async def scan(ticker):
        return {"ticker": ticker, "price": 100}

    result = asyncio.run(
        async_scan_tickers(
            ["AAPL", "MSFT"],
            scan,
            config={"provider_bucket": "test_provider", "rate_limiter": _fast_limiter()},
        )
    )

    assert result["ok"] is True
    assert result["completed"] is True
    assert result["completed_tickers"] == 2
    assert len(result["results"]) == 2


def test_async_scanner_one_failure_does_not_abort_scan():
    async def scan(ticker):
        if ticker == "BAD":
            raise RuntimeError("provider exploded")
        return {"ticker": ticker}

    result = asyncio.run(
        async_scan_tickers(
            ["AAPL", "BAD", "MSFT"],
            scan,
            config={"provider_bucket": "test_provider", "rate_limiter": _fast_limiter()},
        )
    )

    assert result["completed"] is False
    assert "BAD" in result["failed_tickers"]
    assert result["completed_tickers"] == 2
    assert "partial results" in " ".join(result["warnings"]).lower()


def test_async_scanner_captures_ticker_timeout():
    async def scan(ticker):
        await asyncio.sleep(0.05)
        return {"ticker": ticker}

    result = asyncio.run(
        async_scan_tickers(
            ["AAPL"],
            scan,
            config={
                "ticker_timeout_seconds": 0.01,
                "provider_bucket": "test_provider",
                "rate_limiter": _fast_limiter(),
            },
        )
    )

    assert result["completed"] is False
    assert result["timed_out_tickers"] == ["AAPL"]
    assert result["results"][0]["error_type"] == "timeout"


def test_async_scanner_total_timeout_returns_partial_results():
    async def scan(ticker):
        if ticker == "SLOW":
            await asyncio.sleep(0.1)
        return {"ticker": ticker}

    result = asyncio.run(
        async_scan_tickers(
            ["FAST", "SLOW"],
            scan,
            config={
                "max_concurrency": 2,
                "ticker_timeout_seconds": 1,
                "total_timeout_seconds": 0.03,
                "provider_bucket": "test_provider",
                "rate_limiter": _fast_limiter(),
            },
        )
    )

    assert result["completed"] is False
    assert "SLOW" in result["timed_out_tickers"]
    assert result["completed_tickers"] == 1


def test_async_scanner_respects_concurrency_limit():
    active = 0
    max_seen = 0

    async def scan(ticker):
        nonlocal active, max_seen
        active += 1
        max_seen = max(max_seen, active)
        await asyncio.sleep(0.01)
        active -= 1
        return {"ticker": ticker}

    result = asyncio.run(
        async_scan_tickers(
            ["A", "B", "C", "D"],
            scan,
            config={
                "max_concurrency": 2,
                "provider_bucket": "test_provider",
                "rate_limiter": _fast_limiter(),
            },
        )
    )

    assert result["completed"] is True
    assert max_seen <= 2

