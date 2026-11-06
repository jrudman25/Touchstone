"""Cancellation flag against real Redis."""

import asyncio
from uuid import uuid4

from arq.connections import RedisSettings, create_pool

from evalcore.cancellation import cancel_key, is_cancel_requested, request_cancel


def test_cancel_key_format() -> None:
    assert cancel_key("abc") == "run:abc:cancel"


def test_request_cancel_sets_flag_with_ttl(arq_settings: RedisSettings) -> None:
    run_id = uuid4().hex[:24]
    key = cancel_key(run_id)

    async def body() -> None:
        redis = await create_pool(arq_settings)
        try:
            assert await is_cancel_requested(redis, run_id) is False
            await request_cancel(redis, run_id)
            assert await is_cancel_requested(redis, run_id) is True
            ttl: int = await redis.ttl(key)
            assert ttl > 0
        finally:
            await redis.delete(key)
            await redis.aclose()

    asyncio.run(body())
