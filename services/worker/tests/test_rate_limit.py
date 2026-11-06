"""Rate limiter pacing."""

import asyncio
import time

from eval_worker.rate_limit import RateLimiter


def test_unlimited_returns_immediately() -> None:
    async def go() -> None:
        limiter = RateLimiter(None)
        start = time.monotonic()
        for _ in range(3):
            await limiter.acquire()
        assert time.monotonic() - start < 0.05

    asyncio.run(go())


def test_paces_call_starts() -> None:
    async def go() -> None:
        limiter = RateLimiter(1200)  # 50 ms between starts
        start = time.monotonic()
        for _ in range(3):
            await limiter.acquire()
        assert time.monotonic() - start >= 0.1

    asyncio.run(go())
