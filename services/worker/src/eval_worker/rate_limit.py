"""Minimal requests-per-minute limiter for provider calls."""

import asyncio
import time


class RateLimiter:
    """Enforces a minimum interval between call starts.

    Slots are reserved under a lock, then waited outside it, so waiting
    callers do not block reservation order.
    """

    def __init__(self, requests_per_minute: int | None) -> None:
        self._interval = 60.0 / requests_per_minute if requests_per_minute else None
        self._lock = asyncio.Lock()
        self._next_start = 0.0

    async def acquire(self) -> None:
        if self._interval is None:
            return
        async with self._lock:
            now = time.monotonic()
            start = max(now, self._next_start)
            self._next_start = start + self._interval
            wait = start - now
        if wait > 0:
            await asyncio.sleep(wait)
