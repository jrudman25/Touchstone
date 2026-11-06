"""Shared eval-worker test fixtures: real Mongo/Redis, per-test isolation."""

import asyncio
import os
from collections.abc import Iterator
from typing import Any
from uuid import uuid4

import pymongo
import pytest
from arq.connections import create_pool
from pymongo.database import Database

from eval_worker.settings import Settings
from evalcore import (
    DATASET_ROWS,
    RESULTS,
    RUNS,
    redis_settings,
)


@pytest.fixture(scope="session")
def mongo_url_db() -> Iterator[tuple[str, str]]:
    url = os.environ.get("MONGO_URL", "mongodb://127.0.0.1:27017")
    name = f"{os.environ.get('MONGO_DB', 'touchstone')}_test_{uuid4().hex[:8]}"
    yield url, name
    client: pymongo.MongoClient[dict[str, Any]] = pymongo.MongoClient(url)
    try:
        client.drop_database(name)
    finally:
        client.close()


@pytest.fixture()
def settings() -> Settings:
    return Settings(
        mongo_url=os.environ.get("MONGO_URL", "mongodb://127.0.0.1:27017"),
        mongo_db="",
        redis_url=os.environ.get("REDIS_URL", "redis://127.0.0.1:6379/0"),
        run_queue_name=f"arq:test:{uuid4().hex[:8]}",
        events_maxlen=100,
        events_ttl_seconds=120,
    )


@pytest.fixture()
def worker_settings(settings: Settings, mongo_url_db: tuple[str, str]) -> Settings:
    _, name = mongo_url_db
    return Settings(
        mongo_url=settings.mongo_url,
        mongo_db=name,
        redis_url=settings.redis_url,
        run_queue_name=settings.run_queue_name,
        events_maxlen=settings.events_maxlen,
        events_ttl_seconds=settings.events_ttl_seconds,
    )


@pytest.fixture()
def mongo_db(mongo_url_db: tuple[str, str]) -> Iterator[Database[dict[str, Any]]]:
    """Sync access to the test database; clears all run collections per test."""
    url, name = mongo_url_db
    client: pymongo.MongoClient[dict[str, Any]] = pymongo.MongoClient(url)
    try:
        db = client[name]
        for collection in (RUNS, RESULTS, DATASET_ROWS):
            db[collection].delete_many({})
        yield db
    finally:
        client.close()


@pytest.fixture(autouse=True)
def clean_redis_keys(worker_settings: Settings) -> Iterator[None]:
    yield

    async def go() -> None:
        redis = await create_pool(redis_settings(worker_settings.redis_url))
        try:
            keys = await redis.keys("run:*")
            keys += await redis.keys("arq:job:run:*")
            keys += await redis.keys("arq:result:run:*")
            keys += await redis.keys(f"{worker_settings.run_queue_name}:*")
            keys.append(worker_settings.run_queue_name)
            if keys:
                await redis.delete(*keys)
        finally:
            await redis.aclose()

    asyncio.run(go())
