"""End to end: enqueue a run and execute it through a real arq Worker."""

import asyncio
from typing import Any

from arq import func
from arq.connections import create_pool
from arq.worker import create_worker
from pymongo import AsyncMongoClient
from pymongo.database import Database
from worker_fixtures import seed_dataset_rows, seed_run_doc

from eval_worker.run_executor import execute_run
from eval_worker.settings import Settings
from evalcore import (
    DATASET_ROWS,
    RUN_JOB_NAME,
    RUNS,
    enqueue_run,
    redis_settings,
)


def test_run_through_arq_worker_burst(
    worker_settings: Settings,
    mongo_url_db: tuple[str, str],
    mongo_db: Database[dict[str, Any]],
) -> None:
    seed_dataset_rows(mongo_db, 1, [{"question": "q0"}], ["ans"])
    run_id = seed_run_doc(mongo_db, models=[{"model_config_id": 1}], rows=1)
    url, name = mongo_url_db

    async def go() -> None:
        redis = await create_pool(redis_settings(worker_settings.redis_url))
        try:
            assert await enqueue_run(redis, run_id, queue_name=worker_settings.run_queue_name)
        finally:
            await redis.aclose()

        async def startup(ctx: dict[str, Any]) -> None:
            mongo: AsyncMongoClient[dict[str, Any]] = AsyncMongoClient(url, tz_aware=True)
            ctx["db"] = mongo[name]
            ctx["settings"] = worker_settings
            ctx["mongo_client"] = mongo

        async def shutdown(ctx: dict[str, Any]) -> None:
            await ctx["mongo_client"].close()

        worker = create_worker(
            {
                "functions": [func(execute_run, name=RUN_JOB_NAME)],
                "redis_settings": redis_settings(worker_settings.redis_url),
                "queue_name": worker_settings.run_queue_name,
                "on_startup": startup,
                "on_shutdown": shutdown,
                "burst": True,
                "handle_signals": False,
            }
        )
        await worker.async_run()

    asyncio.run(go())

    run = mongo_db[RUNS].find_one()
    assert run is not None and run["status"] == "finished"
    assert mongo_db[DATASET_ROWS].count_documents({}) == 1
