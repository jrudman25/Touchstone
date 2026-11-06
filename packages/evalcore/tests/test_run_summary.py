"""Authoritative summary aggregation against real Mongo."""

import asyncio
from collections.abc import Callable, Coroutine
from typing import Any

import pytest
from bson import ObjectId
from pymongo import AsyncMongoClient
from pymongo.asynchronous.database import AsyncDatabase

from evalcore.run_summary import recompute_run_totals_and_summary

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


def result_doc(
    run_oid: ObjectId,
    model_id: int,
    row: int,
    *,
    error: str | None = None,
    latency: int = 10,
    cost: float = 0.01,
    scores: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    return {
        "run_id": run_oid,
        "model_config_id": model_id,
        "row_index": row,
        "input": {},
        "expected": None,
        "rendered_prompt": "p",
        "output": None if error else "o",
        "usage": None if error else {"input_tokens": 1, "output_tokens": 1},
        "latency_ms": None if error else latency,
        "cost_usd": None if error else cost,
        "error": error,
        "context_limited": False,
        "scores": scores or [],
    }


def test_summary_aggregation(mongo_database: MongoFixture) -> None:
    async def body(db: AsyncDatabase[dict[str, Any]]) -> None:
        run_oid = ObjectId()
        docs = [
            result_doc(
                run_oid,
                1,
                0,
                latency=10,
                cost=0.01,
                scores=[{"scorer_id": 1, "value": 1.0}, {"scorer_id": 2, "value": 0.0}],
            ),
            result_doc(
                run_oid,
                1,
                1,
                latency=20,
                cost=0.03,
                scores=[{"scorer_id": 1, "value": 0.0}, {"scorer_id": 2, "value": None}],
            ),
            result_doc(run_oid, 1, 2, error="boom"),
            result_doc(
                run_oid,
                2,
                0,
                latency=30,
                cost=0.05,
                scores=[{"scorer_id": 1, "value": 0.5}],
            ),
        ]
        await db["results"].insert_many(docs)

        totals, summary = await recompute_run_totals_and_summary(db, str(run_oid))
        assert (totals.done, totals.failed) == (4, 1)
        one = summary["1"]
        assert one.error_count == 1
        assert one.cost_usd == pytest.approx(0.04)
        # Mean over all non-null values: (1.0 + 0.0 + 0.0) / 3; the null is excluded.
        assert one.mean_score == pytest.approx(1 / 3)
        assert one.by_scorer == {"1": pytest.approx(0.5), "2": pytest.approx(0.0)}
        assert one.p95_latency_ms == 20
        two = summary["2"]
        assert two.mean_score == pytest.approx(0.5)
        assert two.error_count == 0
        assert two.cost_usd == pytest.approx(0.05)

    run_in_db(mongo_database, body)


def test_summary_empty_run(mongo_database: MongoFixture) -> None:
    async def body(db: AsyncDatabase[dict[str, Any]]) -> None:
        totals, summary = await recompute_run_totals_and_summary(db, str(ObjectId()))
        assert totals.done == 0 and totals.failed == 0
        assert summary == {}

    run_in_db(mongo_database, body)
