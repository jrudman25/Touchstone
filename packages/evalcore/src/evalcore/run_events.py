"""Run progress events on a Redis Stream.

The worker appends to ``run:{id}:events`` (capped with ``MAXLEN ~``);
FastAPI serves SSE from it later. Two fields per entry: ``type`` (``status``,
``result``, ``summary``) and ``data`` (JSON). ``expire_events`` bounds
retention after a run finishes; ``reset`` recovery is a Phase 3 concern.
"""

import json
from typing import Any

from arq import ArqRedis


def events_key(run_id: str) -> str:
    return f"run:{run_id}:events"


async def publish_event(
    redis: ArqRedis, run_id: str, event_type: str, data: dict[str, Any], *, maxlen: int
) -> None:
    await redis.xadd(
        events_key(run_id),
        {"type": event_type, "data": json.dumps(data, default=str)},
        maxlen=maxlen,
        approximate=True,
    )


async def expire_events(redis: ArqRedis, run_id: str, ttl_seconds: int) -> None:
    await redis.expire(events_key(run_id), ttl_seconds)
