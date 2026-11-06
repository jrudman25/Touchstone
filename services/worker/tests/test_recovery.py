"""Stale-running-run recovery at worker startup."""

import asyncio
from typing import Any

from arq.connections import create_pool
from pymongo.database import Database
from worker_fixtures import seed_run_doc

from eval_worker.recovery import STALE_ERROR, recover_stale_runs
from eval_worker.settings import Settings
from evalcore import RUNS, enqueue_run, redis_settings, run_job_id


def test_stale_running_run_marked_failed(
    worker_settings: Settings, mongo_db: Database[dict[str, Any]]
) -> None:
    seed_run_doc(mongo_db, models=[{"model_config_id": 1}], rows=1)
    mongo_db[RUNS].update_one({}, {"$set": {"status": "running"}})

    async def go() -> None:
        redis = await create_pool(redis_settings(worker_settings.redis_url))
        try:
            await recover_stale_runs(_async_db(worker_settings), redis, worker_settings)
        finally:
            await redis.aclose()

    asyncio.run(go())
    run = mongo_db[RUNS].find_one()
    assert run is not None
    assert run["status"] == "failed" and run["error"] == STALE_ERROR
    assert run["finished_at"] is not None


def _async_db(worker_settings: Settings) -> Any:
    from pymongo import AsyncMongoClient

    return AsyncMongoClient(worker_settings.mongo_url)[worker_settings.mongo_db]


def test_running_run_with_queued_job_is_left_alone(
    worker_settings: Settings, mongo_db: Database[dict[str, Any]]
) -> None:
    run_id = seed_run_doc(mongo_db, models=[{"model_config_id": 1}], rows=1)
    mongo_db[RUNS].update_one({}, {"$set": {"status": "running"}})

    async def go() -> None:
        redis = await create_pool(redis_settings(worker_settings.redis_url))
        try:
            assert await enqueue_run(redis, run_id, queue_name=worker_settings.run_queue_name)
            await recover_stale_runs(_async_db(worker_settings), redis, worker_settings)
        finally:
            await redis.delete(f"arq:job:{run_job_id(run_id)}")
            await redis.aclose()

    asyncio.run(go())
    assert mongo_db[RUNS].find_one()["status"] == "running"  # type: ignore[index]
