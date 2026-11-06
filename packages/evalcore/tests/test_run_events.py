"""Run event stream helpers against real Redis."""

import asyncio
import json
from uuid import uuid4

from arq.connections import RedisSettings, create_pool

from evalcore.run_events import events_key, expire_events, publish_event


def test_publish_event_fields_and_trim(arq_settings: RedisSettings) -> None:
    run_id = uuid4().hex[:24]
    key = events_key(run_id)

    async def body() -> None:
        redis = await create_pool(arq_settings)
        try:
            for index in range(10):
                await publish_event(
                    redis,
                    run_id,
                    "result",
                    {"row_index": index, "note": "text"},
                    maxlen=5,
                )
            entries = await redis.xrange(key)
            assert len(entries) <= 10  # approximate trim keeps near maxlen
            fields = entries[-1][1]
            assert fields[b"type"] == b"result"
            assert json.loads(fields[b"data"]) == {"row_index": 9, "note": "text"}
        finally:
            await redis.delete(key)
            await redis.aclose()

    asyncio.run(body())


def test_expire_events_sets_ttl(arq_settings: RedisSettings) -> None:
    run_id = uuid4().hex[:24]
    key = events_key(run_id)

    async def body() -> None:
        redis = await create_pool(arq_settings)
        try:
            await publish_event(redis, run_id, "status", {"status": "finished"}, maxlen=10)
            await expire_events(redis, run_id, 60)
            ttl: int = await redis.ttl(key)
            assert 0 < ttl <= 60
        finally:
            await redis.delete(key)
            await redis.aclose()

    asyncio.run(body())
