"""Run cancellation flag in Redis.

The worker checks the key between rows; partial results are kept.
"""

from arq import ArqRedis

CANCEL_TTL_SECONDS = 24 * 60 * 60


def cancel_key(run_id: str) -> str:
    return f"run:{run_id}:cancel"


async def request_cancel(redis: ArqRedis, run_id: str) -> None:
    await redis.set(cancel_key(run_id), b"1", ex=CANCEL_TTL_SECONDS)


async def is_cancel_requested(redis: ArqRedis, run_id: str) -> bool:
    count: int = await redis.exists(cancel_key(run_id))
    return count > 0
