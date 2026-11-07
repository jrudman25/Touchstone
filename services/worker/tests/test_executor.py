"""execute_run against real Mongo/Redis with injected provider factories."""

import asyncio
from typing import Any, cast

from pymongo.database import Database
from worker_fixtures import make_ctx, seed_dataset_rows, seed_run_doc

from eval_worker.run_executor import execute_run
from eval_worker.settings import Settings
from evalcore import (
    RESULTS,
    RUNS,
    GenerationRequest,
    MockProvider,
    cancel_key,
    events_key,
    is_cancel_requested,
    request_cancel,
)

QUESTIONS = [{"question": f"q{i}"} for i in range(5)]
EXPECTED = ["Paris", "4", "blue", "42", "yes"]


def model(mid: int, **kw: Any) -> dict[str, Any]:
    return {"model_config_id": mid, **kw}


def mock_factory(model_obj: Any, *, seed: int, answers: Any) -> MockProvider:
    return MockProvider(seed=seed, answers=answers, accuracy=0.5)


def run_exec(ctx_runner: Any, run_id: str) -> None:
    ctx_runner(lambda ctx: execute_run(ctx, run_id))


def docs(mongo_db: Database[dict[str, Any]], **query: Any) -> list[dict[str, Any]]:
    cursor = mongo_db[RESULTS].find(query)
    return list(cursor.sort([("model_config_id", 1), ("row_index", 1)]))


def setup_two_model_run(mongo_db: Database[dict[str, Any]]) -> str:
    seed_dataset_rows(mongo_db, 1, QUESTIONS, EXPECTED)
    return cast(
        str,
        seed_run_doc(
            mongo_db,
            models=[model(1), model(2)],
            rows=5,
            scorers=[
                {"scorer_id": 1, "name": "exact", "kind": "exact", "params": {}},
                {"scorer_id": 2, "name": "contains", "kind": "contains", "params": {}},
            ],
        ),
    )


def test_happy_path(
    worker_settings: Settings,
    mongo_url_db: tuple[str, str],
    mongo_db: Database[dict[str, Any]],
) -> None:
    run_id = setup_two_model_run(mongo_db)
    run_exec(make_ctx(worker_settings, mongo_url_db, provider_factory=mock_factory), run_id)

    results = docs(mongo_db)
    assert len(results) == 10
    assert {(r["model_config_id"], r["row_index"]) for r in results} == {
        (m, i) for m in (1, 2) for i in range(5)
    }
    direct = MockProvider(seed=7, answers={f"Q: q{i}": EXPECTED[i] for i in range(5)}, accuracy=0.5)
    for result in results:
        generated = asyncio.run(
            direct.generate(
                GenerationRequest(
                    model_name=f"mock-{result['model_config_id']}",
                    system_message="sys",
                    prompt=result["rendered_prompt"],
                    temperature=0.0,
                    max_tokens=256,
                )
            )
        )
        assert result["output"] == generated.output
        exact = next(s for s in result["scores"] if s["scorer_id"] == 1)
        assert (exact["value"] == 1.0) == (result["output"] == result["expected"])

    run = mongo_db[RUNS].find_one({"status": "finished"})
    assert run is not None and run["finished_at"] is not None
    assert run["totals"] == {"rows": 10, "done": 10, "failed": 0}
    summary = run["summary"]
    for mid in ("1", "2"):
        assert summary[mid]["error_count"] == 0
        assert summary[mid]["p95_latency_ms"] is not None
        assert summary[mid]["cost_usd"] > 0
        assert set(summary[mid]["by_scorer"]) == {"1", "2"}

    async def read_events() -> tuple[list[tuple[bytes, dict[bytes, Any]]], int]:
        from arq.connections import create_pool

        from evalcore import redis_settings

        redis = await create_pool(redis_settings(worker_settings.redis_url))
        try:
            entries = await redis.xrange(events_key(run_id))
            ttl: int = await redis.ttl(events_key(run_id))
            return entries, ttl
        finally:
            await redis.aclose()

    events, ttl = asyncio.run(read_events())
    types = [fields[b"type"].decode() for _, fields in events]
    assert types[0] == "status" and types[-2:] == ["status", "summary"]
    assert types.count("result") == 10
    assert ttl > 0
    last_result = next(
        fields[b"data"] for _, fields in reversed(events) if fields[b"type"] == b"result"
    )
    import json

    assert json.loads(last_result)["totals"] == {
        "done": run["totals"]["done"],
        "failed": run["totals"]["failed"],
    }


def test_retry_keeps_existing_results(
    worker_settings: Settings,
    mongo_url_db: tuple[str, str],
    mongo_db: Database[dict[str, Any]],
) -> None:
    run_id = setup_two_model_run(mongo_db)
    mongo_db[RESULTS].insert_one(
        {
            "run_id": __import__("bson").ObjectId(run_id),
            "model_config_id": 1,
            "row_index": 2,
            "input": {"question": "q2"},
            "expected": "blue",
            "rendered_prompt": "Q: q2",
            "output": "PRE-EXISTING",
            "usage": None,
            "latency_ms": None,
            "cost_usd": None,
            "error": None,
            "context_limited": False,
            "scores": [],
        }
    )
    run_exec(make_ctx(worker_settings, mongo_url_db, provider_factory=mock_factory), run_id)
    results = docs(mongo_db)
    assert len(results) == 10
    kept = mongo_db[RESULTS].find_one({"model_config_id": 1, "row_index": 2})
    assert kept is not None and kept["output"] == "PRE-EXISTING"
    run = mongo_db[RUNS].find_one()
    assert run is not None and run["totals"]["done"] == 10


def test_cancelled_while_queued_does_nothing(
    worker_settings: Settings,
    mongo_url_db: tuple[str, str],
    mongo_db: Database[dict[str, Any]],
) -> None:
    run_id = setup_two_model_run(mongo_db)
    mongo_db[RUNS].update_one({}, {"$set": {"status": "cancelled"}})
    import redis as sync_redis

    key = cancel_key(run_id)
    sync_redis.from_url(  # type: ignore[no-untyped-call]
        worker_settings.redis_url
    ).set(key, b"1")
    run_exec(make_ctx(worker_settings, mongo_url_db), run_id)
    assert mongo_db[RESULTS].count_documents({}) == 0
    assert mongo_db[RUNS].find_one()["status"] == "cancelled"  # type: ignore[index]
    assert not sync_redis.from_url(  # type: ignore[no-untyped-call]
        worker_settings.redis_url
    ).exists(key)


def test_cancel_flag_before_start(
    worker_settings: Settings,
    mongo_url_db: tuple[str, str],
    mongo_db: Database[dict[str, Any]],
) -> None:
    run_id = setup_two_model_run(mongo_db)

    async def seed_flag() -> None:
        from arq.connections import create_pool

        from evalcore import redis_settings

        redis = await create_pool(redis_settings(worker_settings.redis_url))
        try:
            await request_cancel(redis, run_id)
        finally:
            await redis.aclose()

    asyncio.run(seed_flag())
    run_exec(make_ctx(worker_settings, mongo_url_db), run_id)
    assert mongo_db[RESULTS].count_documents({}) == 0
    assert mongo_db[RUNS].find_one()["status"] == "cancelled"  # type: ignore[index]

    async def flag_gone() -> bool:
        from arq.connections import create_pool

        from evalcore import redis_settings

        redis = await create_pool(redis_settings(worker_settings.redis_url))
        try:
            return await is_cancel_requested(redis, run_id)
        finally:
            await redis.aclose()

    assert asyncio.run(flag_gone()) is False


def test_mid_run_cancel(
    worker_settings: Settings,
    mongo_url_db: tuple[str, str],
    mongo_db: Database[dict[str, Any]],
) -> None:
    inputs = [{"question": f"q{i}"} for i in range(10)]
    expected = [f"a{i}" for i in range(10)]
    seed_dataset_rows(mongo_db, 1, inputs, expected)
    run_id = seed_run_doc(mongo_db, models=[model(1, max_concurrency=1)], rows=10)
    calls = {"n": 0}

    def cancelling_factory(model_obj: Any, *, seed: int, answers: Any) -> MockProvider:
        class Cancelling(MockProvider):
            async def generate(self, request: GenerationRequest) -> Any:
                calls["n"] += 1
                if calls["n"] == 3:
                    import redis as sync_redis

                    from evalcore import cancel_key

                    # Blocking on purpose: test-only flag write from inside a
                    # provider call, keeping the write on this event loop.
                    sync_redis.from_url(  # type: ignore[no-untyped-call]
                        worker_settings.redis_url
                    ).set(cancel_key(run_id), b"1")
                return await super().generate(request)

        return Cancelling(seed=seed, answers=answers)

    run_exec(
        make_ctx(worker_settings, mongo_url_db, provider_factory=cancelling_factory),
        run_id,
    )

    run = mongo_db[RUNS].find_one()
    assert run is not None and run["status"] == "cancelled"
    assert mongo_db[RESULTS].count_documents({}) == 3
    assert run["totals"]["done"] == 3


def test_provider_failure_marks_all_results(
    worker_settings: Settings,
    mongo_url_db: tuple[str, str],
    mongo_db: Database[dict[str, Any]],
) -> None:
    run_id = setup_two_model_run(mongo_db)

    def failing_factory(model_obj: Any, *, seed: int, answers: Any) -> MockProvider:
        return MockProvider(seed=seed, answers=answers, fail_rate=1.0)

    run_exec(make_ctx(worker_settings, mongo_url_db, provider_factory=failing_factory), run_id)
    run = mongo_db[RUNS].find_one()
    assert run is not None and run["status"] == "finished"
    assert run["totals"]["done"] == 10 and run["totals"]["failed"] == 10
    for mid in ("1", "2"):
        assert run["summary"][mid]["mean_score"] is None
        assert run["summary"][mid]["error_count"] == 5
    for result in docs(mongo_db):
        assert result["error"] == "Mock provider failure"


def test_unsupported_provider_kind_errors_results(
    worker_settings: Settings,
    mongo_url_db: tuple[str, str],
    mongo_db: Database[dict[str, Any]],
) -> None:
    seed_dataset_rows(mongo_db, 1, QUESTIONS, EXPECTED)
    run_id = seed_run_doc(mongo_db, models=[model(1, provider_kind="ollama")], rows=5)
    run_exec(make_ctx(worker_settings, mongo_url_db), run_id)  # default factory
    errored = {"error": "Provider kind ollama is not supported yet"}
    assert mongo_db[RESULTS].count_documents(errored) == 5


def test_missing_variable_row_errors_only_that_row(
    worker_settings: Settings,
    mongo_url_db: tuple[str, str],
    mongo_db: Database[dict[str, Any]],
) -> None:
    inputs = [{"question": "q0"}, {"other": 1}, *QUESTIONS[2:]]
    seed_dataset_rows(mongo_db, 1, inputs, EXPECTED)
    run_id = seed_run_doc(mongo_db, models=[model(1)], rows=5)
    run_exec(make_ctx(worker_settings, mongo_url_db, provider_factory=mock_factory), run_id)
    results = {r["row_index"]: r for r in docs(mongo_db)}
    assert results[1]["error"] is not None and "question" in results[1]["error"]
    assert all(results[i]["error"] is None for i in (0, 2, 3, 4))


def test_context_limited(
    worker_settings: Settings,
    mongo_url_db: tuple[str, str],
    mongo_db: Database[dict[str, Any]],
) -> None:
    seed_dataset_rows(mongo_db, 1, QUESTIONS, EXPECTED)
    run_id = seed_run_doc(mongo_db, models=[model(1, context_length=4)], rows=5)
    run_exec(make_ctx(worker_settings, mongo_url_db, provider_factory=mock_factory), run_id)
    assert all(r["context_limited"] for r in docs(mongo_db))


def test_fewer_rows_than_expected_fails_run(
    worker_settings: Settings,
    mongo_url_db: tuple[str, str],
    mongo_db: Database[dict[str, Any]],
) -> None:
    seed_dataset_rows(mongo_db, 1, QUESTIONS[:3], EXPECTED[:3])
    run_id = seed_run_doc(mongo_db, models=[model(1)], rows=5)
    run_exec(make_ctx(worker_settings, mongo_url_db, provider_factory=mock_factory), run_id)
    run = mongo_db[RUNS].find_one()
    assert run is not None and run["status"] == "failed"
    assert "3 rows" in run["error"] and "expected 5" in run["error"]


def test_max_concurrency_keeps_each_result_once(
    worker_settings: Settings,
    mongo_url_db: tuple[str, str],
    mongo_db: Database[dict[str, Any]],
) -> None:
    seed_dataset_rows(mongo_db, 1, QUESTIONS, EXPECTED)
    run_id = seed_run_doc(mongo_db, models=[model(1, max_concurrency=3)], rows=5)
    run_exec(make_ctx(worker_settings, mongo_url_db, provider_factory=mock_factory), run_id)
    assert mongo_db[RESULTS].count_documents({}) == 5
