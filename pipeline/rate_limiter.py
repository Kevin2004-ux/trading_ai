from __future__ import annotations

import asyncio
from collections import defaultdict, deque
from contextlib import asynccontextmanager
import os
import time
from typing import AsyncIterator


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, default))
    except (TypeError, ValueError):
        return default


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, default))
    except (TypeError, ValueError):
        return default


DEFAULT_RATE_LIMIT_BUCKETS = {
    "ibkr_market_data": {
        "max_calls_per_second": _env_float("IBKR_REQUESTS_PER_SECOND", 2.0),
        "max_concurrent_calls": _env_int("IBKR_MAX_CONCURRENT_REQUESTS", 3),
    },
    "ibkr_options_data": {
        "max_calls_per_second": _env_float("IBKR_REQUESTS_PER_SECOND", 2.0),
        "max_concurrent_calls": _env_int("IBKR_MAX_CONCURRENT_REQUESTS", 3),
    },
    "research_api": {
        "max_calls_per_second": _env_float("RESEARCH_API_REQUESTS_PER_SECOND", 3.0),
        "max_concurrent_calls": 3,
    },
    "ai_model": {
        "max_calls_per_second": _env_float("AI_REQUESTS_PER_SECOND", 1.0),
        "max_concurrent_calls": 1,
    },
}


class AsyncRateLimiter:
    """Small async token/window limiter with provider-specific buckets."""

    def __init__(self, buckets: dict | None = None):
        merged = {name: dict(config) for name, config in DEFAULT_RATE_LIMIT_BUCKETS.items()}
        if isinstance(buckets, dict):
            for name, config in buckets.items():
                if isinstance(config, dict):
                    merged[str(name)] = {**merged.get(str(name), {}), **config}

        self.buckets = merged
        self._locks = defaultdict(asyncio.Lock)
        self._calls = defaultdict(deque)
        self._semaphores = {
            name: asyncio.Semaphore(max(1, int(config.get("max_concurrent_calls") or 1)))
            for name, config in self.buckets.items()
        }

    def _config_for(self, bucket: str) -> dict:
        return self.buckets.get(bucket) or self.buckets["ibkr_market_data"]

    async def wait(self, bucket: str = "ibkr_market_data") -> None:
        config = self._config_for(bucket)
        max_calls = max(float(config.get("max_calls_per_second") or 1.0), 0.01)
        spacing = 1.0 / max_calls

        async with self._locks[bucket]:
            now = time.monotonic()
            calls = self._calls[bucket]
            while calls and now - calls[0] >= 1.0:
                calls.popleft()

            if calls:
                elapsed = now - calls[-1]
                if elapsed < spacing:
                    await asyncio.sleep(spacing - elapsed)
                    now = time.monotonic()
                    while calls and now - calls[0] >= 1.0:
                        calls.popleft()

            calls.append(time.monotonic())

    @asynccontextmanager
    async def limit(self, bucket: str = "ibkr_market_data") -> AsyncIterator[None]:
        semaphore = self._semaphores.get(bucket)
        if semaphore is None:
            config = self._config_for(bucket)
            semaphore = asyncio.Semaphore(max(1, int(config.get("max_concurrent_calls") or 1)))
            self._semaphores[bucket] = semaphore

        async with semaphore:
            await self.wait(bucket)
            yield

