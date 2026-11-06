"""Shared helpers for worker tests (kept out of conftest to avoid name clashes)."""

import asyncio
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from arq.connections import create_pool
from pymongo import AsyncMongoClient
from pymongo.database import Database

from eval_worker.settings import Settings
from evalcore import DATASET_ROWS, RUNS, redis_settings


def make_ctx(
    settings: Settings,
    mongo_url_db: tuple[str, str],
    **overrides: Any,
) -> Callable[[Callable[..., Any]], Any]:
    """Run an async callable with a worker-shaped ctx (async db + arq redis)."""
    url, name = mongo_url_db

    def runner(coro: Callable[..., Any]) -> Any:
        async def go() -> Any:
            mongo: AsyncMongoClient[dict[str, Any]] = AsyncMongoClient(url, tz_aware=True)
            redis = await create_pool(redis_settings(settings.redis_url))
            try:
                ctx: dict[str, Any] = {
                    "db": mongo[name],
                    "redis": redis,
                    "settings": settings,
                }
                ctx.update(overrides)
                return await coro(ctx)
            finally:
                await redis.aclose()
                await mongo.close()

        return asyncio.run(go())

    return runner


def seed_run_doc(
    mongo_db: Database[dict[str, Any]],
    models: list[dict[str, Any]],
    rows: int,
    scorers: list[dict[str, Any]] | None = None,
    **overrides: Any,
) -> str:
    def model_fields(**kw: Any) -> dict[str, Any]:
        mid: int = kw.pop("model_config_id")
        base: dict[str, Any] = {
            "model_config_id": mid,
            "provider_id": 1,
            "provider_name": "mock",
            "provider_kind": "mock",
            "model_name": f"mock-{mid}",
            "temperature": 0.0,
            "max_tokens": 256,
            "context_length": 4096,
            "input_price_per_1k": 0.001,
            "output_price_per_1k": 0.002,
            "max_concurrency": 1,
            "requests_per_minute": None,
            "base_url": "",
            "api_key_env": "",
            "digest": None,
        }
        base.update(kw)
        return base

    doc: dict[str, Any] = {
        "organization_id": 1,
        "project_id": 1,
        "prompt_version_id": 1,
        "dataset_id": 1,
        "model_config_ids": [m["model_config_id"] for m in models],
        "scorer_ids": [s["scorer_id"] for s in (scorers or [])],
        "snapshot": {
            "prompt": {
                "prompt_version_id": 1,
                "template_id": 1,
                "number": 1,
                "system_message": "sys",
                "body": "Q: {{question}}",
                "variables": ["question"],
            },
            "models": [model_fields(**m) for m in models],
            "scorers": scorers or [],
            "seed": 7,
        },
        "status": "queued",
        "created_by": 7,
        "created_at": datetime.now(UTC),
        "finished_at": None,
        "totals": {"rows": rows * len(models), "done": 0, "failed": 0},
        "summary": {},
        "error": None,
    }
    doc.update(overrides)
    return str(mongo_db[RUNS].insert_one(doc).inserted_id)


def seed_dataset_rows(
    mongo_db: Database[dict[str, Any]],
    dataset_id: int,
    inputs: list[dict[str, Any]],
    expected: list[str | None] | None = None,
) -> None:
    mongo_db[DATASET_ROWS].insert_many(
        [
            {
                "dataset_id": dataset_id,
                "row_index": i,
                "input": inputs[i],
                "expected": expected[i] if expected else None,
            }
            for i in range(len(inputs))
        ]
    )
