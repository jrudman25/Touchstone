"""run_store Mongo helpers against real Mongo."""

import asyncio
from collections.abc import Callable, Coroutine
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from bson import ObjectId
from pymongo import AsyncMongoClient
from pymongo.asynchronous.database import AsyncDatabase

from evalcore.mongo import RESULTS
from evalcore.run_store import (
    cancel_queued_run,
    delete_run,
    get_run,
    insert_run,
    list_results,
    list_runs,
    upsert_result,
)

MongoFixture = tuple[str, str]
DbTest = Callable[[AsyncDatabase[dict[str, Any]]], Coroutine[Any, Any, Any]]


def run_in_db(mongo_database: MongoFixture, body: DbTest) -> None:
    url, name = mongo_database

    async def main() -> None:
        client: AsyncMongoClient[dict[str, Any]] = AsyncMongoClient(url, tz_aware=True)
        try:
            await body(client[name])
        finally:
            await client.close()

    asyncio.run(main())


def run_fields(project_id: int, org: int = 1, **overrides: Any) -> dict[str, Any]:
    fields: dict[str, Any] = {
        "organization_id": org,
        "project_id": project_id,
        "prompt_version_id": 1,
        "dataset_id": 1,
        "model_config_ids": [1],
        "scorer_ids": [],
        "snapshot": {
            "prompt": {
                "prompt_version_id": 1,
                "template_id": 1,
                "number": 1,
                "system_message": "",
                "body": "b",
                "variables": [],
            },
            "models": [],
            "scorers": [],
            "seed": 0,
        },
        "status": "queued",
        "created_by": 1,
        "created_at": datetime(2026, 11, 1, 12, 0, 0, tzinfo=UTC),
        "finished_at": None,
        "totals": {"rows": 0, "done": 0, "failed": 0},
        "summary": {},
        "error": None,
    }
    fields.update(overrides)
    return fields


def test_insert_get_delete_run(mongo_database: MongoFixture) -> None:
    project_id = int(uuid4().hex[:6], 16) % 100_000

    async def body(db: AsyncDatabase[dict[str, Any]]) -> None:
        run = await insert_run(db, run_fields(project_id))
        assert run.id and run.status.value == "queued"
        fetched = await get_run(db, run.id)
        assert fetched == run
        assert await get_run(db, "not-hex") is None
        await delete_run(db, run.id)
        assert await get_run(db, run.id) is None

    run_in_db(mongo_database, body)


def test_list_runs_ordering_paging_and_org_filter(mongo_database: MongoFixture) -> None:
    project_id = int(uuid4().hex[:6], 16) % 100_000

    async def body(db: AsyncDatabase[dict[str, Any]]) -> None:
        created = []
        for index in range(3):
            fields = run_fields(project_id, created_at=datetime(2026, 11, index + 1, tzinfo=UTC))
            created.append(await insert_run(db, fields))
        await insert_run(db, run_fields(project_id, org=99))
        await insert_run(db, run_fields(project_id + 1))
        newest_first = [created[2].id, created[1].id, created[0].id]

        runs, before = await list_runs(
            db, project_id=project_id, organization_ids=[1], before=None, limit=2
        )
        assert [r.id for r in runs] == newest_first[:2]
        assert before == created[1].id

        runs, before = await list_runs(
            db, project_id=project_id, organization_ids=[1], before=before, limit=2
        )
        assert [r.id for r in runs] == newest_first[2:]
        assert before is None

        runs, before = await list_runs(
            db,
            project_id=project_id,
            organization_ids=[1],
            before="f" * 24,
            limit=2,
        )
        assert runs == [] and before is None

    run_in_db(mongo_database, body)


def test_cancel_queued_run_only_from_queued(mongo_database: MongoFixture) -> None:
    project_id = int(uuid4().hex[:6], 16) % 100_000
    now = datetime(2026, 11, 5, tzinfo=UTC)

    async def body(db: AsyncDatabase[dict[str, Any]]) -> None:
        run = await insert_run(db, run_fields(project_id))
        cancelled = await cancel_queued_run(db, run.id, now)
        assert cancelled is not None
        assert cancelled.status.value == "cancelled" and cancelled.finished_at == now
        assert await cancel_queued_run(db, run.id, now) is None
        running = await insert_run(db, run_fields(project_id, status="running"))
        assert await cancel_queued_run(db, running.id, now) is None

    run_in_db(mongo_database, body)


def result_fields(run_id: str, model_id: int, row_index: int, **overrides: Any) -> dict[str, Any]:
    fields: dict[str, Any] = {
        "run_id": run_id,
        "model_config_id": model_id,
        "row_index": row_index,
        "input": {"q": "x"},
        "expected": "e",
        "rendered_prompt": "p",
        "output": "o",
        "usage": {"input_tokens": 1, "output_tokens": 1},
        "latency_ms": 5,
        "cost_usd": 0.0,
        "error": None,
        "context_limited": False,
        "scores": [],
    }
    fields.update(overrides)
    return fields


def test_upsert_result_idempotent_and_list_results(mongo_database: MongoFixture) -> None:
    async def body(db: AsyncDatabase[dict[str, Any]]) -> None:
        run = await insert_run(db, run_fields(int(uuid4().hex[:6], 16) % 100_000))
        fields = result_fields(run.id, 1, 0, output="first")
        await upsert_result(db, fields)
        await upsert_result(db, result_fields(run.id, 1, 0, output="second"))
        docs = await db[RESULTS].count_documents({"run_id": ObjectId(run.id)})
        assert docs == 1
        stored = await db[RESULTS].find_one({"run_id": ObjectId(run.id)})
        assert stored is not None and stored["output"] == "second"

        await upsert_result(
            db, result_fields(run.id, 1, 1, scores=[{"scorer_id": 1, "value": 0.2}])
        )
        await upsert_result(
            db, result_fields(run.id, 1, 2, scores=[{"scorer_id": 1, "value": None}])
        )
        await upsert_result(db, result_fields(run.id, 2, 0, error="boom"))

        results, after = await list_results(db, run.id, after=None, limit=2)
        assert [(r.model_config_id, r.row_index) for r in results] == [(1, 0), (1, 1)]
        assert after == (1, 1)
        results, after = await list_results(db, run.id, after=after, limit=2)
        assert [(r.model_config_id, r.row_index) for r in results] == [(1, 2), (2, 0)]
        assert after is None

        results, _ = await list_results(db, run.id, errors_only=True, after=None, limit=10)
        assert [(r.model_config_id, r.row_index) for r in results] == [(2, 0)]
        results, _ = await list_results(
            db, run.id, scorer_id=1, max_score=0.5, after=None, limit=10
        )
        assert [(r.model_config_id, r.row_index) for r in results] == [(1, 1)]
        results, _ = await list_results(db, run.id, model_config_id=1, after=None, limit=10)
        assert len(results) == 3

    run_in_db(mongo_database, body)
