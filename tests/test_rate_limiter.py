import asyncio
import time

from pipeline.rate_limiter import AsyncRateLimiter


def test_rate_limiter_waits_instead_of_allowing_unlimited_calls():
    async def run_limited_calls():
        limiter = AsyncRateLimiter(
            {
                "test_provider": {
                    "max_calls_per_second": 20,
                    "max_concurrent_calls": 1,
                }
            }
        )
        started = time.monotonic()
        await limiter.wait("test_provider")
        await limiter.wait("test_provider")
        return time.monotonic() - started

    elapsed = asyncio.run(run_limited_calls())

    assert elapsed >= 0.04


def test_rate_limiter_respects_provider_concurrency():
    active = 0
    max_seen = 0

    async def run_limited_work():
        nonlocal active, max_seen
        limiter = AsyncRateLimiter(
            {
                "test_provider": {
                    "max_calls_per_second": 1000,
                    "max_concurrent_calls": 2,
                }
            }
        )

        async def work():
            nonlocal active, max_seen
            async with limiter.limit("test_provider"):
                active += 1
                max_seen = max(max_seen, active)
                await asyncio.sleep(0.01)
                active -= 1

        await asyncio.gather(*(work() for _ in range(5)))

    asyncio.run(run_limited_work())

    assert max_seen <= 2

