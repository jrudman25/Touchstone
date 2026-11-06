"""arq enqueue seam: deterministic job ids against real Redis."""

import asyncio
from uuid import uuid4

from arq.connections import RedisSettings, create_pool
from arq.constants import default_queue_name
from arq.jobs import Job, JobStatus

from evalcore.jobs import enqueue_run, run_job_id


def test_enqueue_run_queues_once(arq_settings: RedisSettings) -> None:
    run_id = uuid4().hex[:24]
    queue = f"arq:test:{uuid4().hex[:8]}"

    async def body() -> None:
        redis = await create_pool(arq_settings)
        try:
            assert await enqueue_run(redis, run_id, queue_name=queue) is True
            job = Job(run_job_id(run_id), redis, _queue_name=queue)
            assert await job.status() == JobStatus.queued
            assert await enqueue_run(redis, run_id, queue_name=queue) is False
        finally:
            await redis.delete(f"arq:job:{run_job_id(run_id)}", queue)
            await redis.aclose()

    asyncio.run(body())


def test_enqueue_run_uses_default_queue(arq_settings: RedisSettings) -> None:
    run_id = uuid4().hex[:24]

    async def body() -> None:
        redis = await create_pool(arq_settings)
        try:
            assert await enqueue_run(redis, run_id) is True
            job = Job(run_job_id(run_id), redis)
            assert await job.status() == JobStatus.queued
        finally:
            await redis.delete(f"arq:job:{run_job_id(run_id)}")
            await redis.zrem(default_queue_name, run_job_id(run_id))
            await redis.aclose()

    asyncio.run(body())


def test_run_job_id_format() -> None:
    assert run_job_id("abc123") == "run:abc123"
