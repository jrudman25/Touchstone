"""Run endpoints: create validation, snapshot, history, results, cancel."""

import asyncio
import time
from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Any, cast

import jwt
import pytest
from arq.connections import ArqRedis, create_pool
from arq.jobs import Job, JobStatus
from bson import ObjectId
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pymongo import AsyncMongoClient
from pymongo.database import Database
from redis.asyncio.connection import ConnectionPool

from eval_api.settings import Settings
from evalcore import (
    RESULTS,
    RUNS,
    DatasetRowInput,
    cancel_key,
    insert_dataset_rows,
    redis_settings,
    run_job_id,
)

ORG = 1
RUNS_URL = "/api/eval/runs"


def _claims(**overrides: Any) -> dict[str, Any]:
    now = int(time.time())
    claims: dict[str, Any] = {
        "user_id": "7",
        "orgs": {str(ORG): "editor"},
        "token_type": "access",
        "jti": "jti-123",
        "exp": now + 300,
        "iat": now,
    }
    claims.update(overrides)
    return claims


def _mint(private_pem: str, claims: dict[str, Any]) -> str:
    return jwt.encode(claims, private_pem, algorithm="RS256")


def _bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture()
def token(rsa_keypair: tuple[str, str]) -> str:
    private, _ = rsa_keypair
    return _mint(private, _claims())


@pytest.fixture()
def viewer_token(rsa_keypair: tuple[str, str]) -> str:
    private, _ = rsa_keypair
    return _mint(private, _claims(orgs={str(ORG): "viewer"}))


@pytest.fixture(autouse=True)
def clean_run_collections(mongo_db: Database[dict[str, Any]]) -> None:
    mongo_db[RUNS].delete_many({})
    mongo_db[RESULTS].delete_many({})


@pytest.fixture(autouse=True)
def clean_redis_keys(settings: Settings) -> Iterator[None]:
    """Delete this test's queue key and any run job/cancel keys afterwards."""
    yield

    async def go() -> None:
        redis = await create_pool(redis_settings(settings.redis_url))
        try:
            keys = await redis.keys("arq:job:run:*")
            keys += await redis.keys("run:*")
            keys.append(settings.run_queue_name)
            if keys:
                await redis.delete(*keys)
        finally:
            await redis.aclose()

    asyncio.run(go())


def seed_fake_records(fake_records: Any) -> None:
    fake_records.add("projects", 1, {"id": 1, "organization": ORG, "name": "proj"})
    fake_records.add("prompt-templates", 1, {"id": 1, "project": 1, "name": "t"})
    fake_records.add(
        "prompt-versions",
        1,
        {
            "id": 1,
            "template": 1,
            "system_message": "sys",
            "body": "Q: {{question}}",
            "number": 1,
            "variables": ["question"],
        },
    )
    fake_records.add_dataset(7, organization=ORG, project=1, row_count=2)
    for provider_id in (1, 2):
        fake_records.add(
            "providers",
            provider_id,
            {
                "id": provider_id,
                "organization": ORG,
                "name": f"prov{provider_id}",
                "kind": "mock",
                "base_url": "",
                "api_key_env": "",
                "max_concurrency": 1,
                "requests_per_minute": None,
            },
        )
    fake_records.add(
        "models",
        1,
        {
            "id": 1,
            "provider": 1,
            "model_name": "mock-1",
            "temperature": 0.5,
            "max_tokens": 64,
            "context_length": 4096,
            "input_price_per_1k": "0.002000",
            "output_price_per_1k": "0.003000",
        },
    )
    fake_records.add(
        "models",
        2,
        {
            "id": 2,
            "provider": 2,
            "model_name": "mock-2",
            "temperature": 0.0,
            "max_tokens": 32,
            "context_length": 2048,
            "input_price_per_1k": "0.000000",
            "output_price_per_1k": "0.000000",
        },
    )
    fake_records.add(
        "scorers", 1, {"id": 1, "project": 1, "name": "exact", "kind": "exact", "params": {}}
    )


def seed_rows(settings: Settings, dataset_id: int = 7, with_question: bool = True) -> None:
    async def body() -> None:
        client: AsyncMongoClient[dict[str, Any]] = AsyncMongoClient(settings.mongo_url)
        try:
            rows = [
                DatasetRowInput.model_validate(
                    {"input": ({"question": f"q{i}"} if with_question else {"other": i})}
                )
                for i in range(2)
            ]
            await insert_dataset_rows(client[settings.mongo_db], dataset_id, rows)
        finally:
            await client.close()

    asyncio.run(body())


def run_body(**overrides: Any) -> dict[str, Any]:
    body: dict[str, Any] = {
        "project_id": 1,
        "prompt_version_id": 1,
        "dataset_id": 7,
        "model_config_ids": [1],
        "scorer_ids": [1],
        "seed": 3,
    }
    body.update(overrides)
    return body


def job_status(settings: Settings, run_id: str, delete: bool = True) -> JobStatus:
    async def go() -> JobStatus:
        redis = await create_pool(redis_settings(settings.redis_url))
        try:
            status = await Job(
                run_job_id(run_id), redis, _queue_name=settings.run_queue_name
            ).status()
            if delete:
                await redis.delete(f"arq:job:{run_job_id(run_id)}")
            return status
        finally:
            await redis.aclose()

    return asyncio.run(go())


def redis_keys_exist(settings: Settings, *keys: str) -> bool:
    async def go() -> bool:
        redis = await create_pool(redis_settings(settings.redis_url))
        try:
            count: int = await redis.exists(*keys)
            return count > 0
        finally:
            await redis.aclose()

    return asyncio.run(go())


def delete_redis_keys(settings: Settings, *keys: str) -> None:
    async def go() -> None:
        redis = await create_pool(redis_settings(settings.redis_url))
        try:
            await redis.delete(*keys)
        finally:
            await redis.aclose()

    asyncio.run(go())


def insert_run_doc(mongo_db: Database[dict[str, Any]], org: int = ORG, **overrides: Any) -> str:
    doc: dict[str, Any] = {
        "organization_id": org,
        "project_id": 1,
        "prompt_version_id": 1,
        "dataset_id": 7,
        "model_config_ids": [1],
        "scorer_ids": [1],
        "snapshot": {
            "prompt": {
                "prompt_version_id": 1,
                "template_id": 1,
                "number": 1,
                "system_message": "sys",
                "body": "b",
                "variables": [],
            },
            "models": [],
            "scorers": [],
            "seed": 0,
        },
        "status": "queued",
        "created_by": 7,
        "created_at": datetime.now(UTC),
        "finished_at": None,
        "totals": {"rows": 2, "done": 0, "failed": 0},
        "summary": {},
        "error": None,
    }
    doc.update(overrides)
    return str(mongo_db[RUNS].insert_one(doc).inserted_id)


def test_create_run_happy_path(
    client: TestClient,
    fake_records: Any,
    settings: Settings,
    mongo_db: Database[dict[str, Any]],
    token: str,
) -> None:
    seed_fake_records(fake_records)
    seed_rows(settings)
    response = client.post(RUNS_URL, json=run_body(model_config_ids=[2, 1]), headers=_bearer(token))
    assert response.status_code == 201, response.text
    run = response.json()
    assert run["status"] == "queued"
    assert run["created_by"] == 7
    assert run["totals"] == {"rows": 4, "done": 0, "failed": 0}
    snapshot = run["snapshot"]
    assert snapshot["seed"] == 3
    assert snapshot["prompt"]["system_message"] == "sys"
    assert snapshot["prompt"]["variables"] == ["question"]
    assert [m["model_config_id"] for m in snapshot["models"]] == [2, 1]
    for model in snapshot["models"]:
        assert model["provider_kind"] == "mock"
        assert model["digest"] is None
    model_one = snapshot["models"][1]
    assert model_one["input_price_per_1k"] == 0.002
    assert model_one["output_price_per_1k"] == 0.003
    assert [s["scorer_id"] for s in snapshot["scorers"]] == [1]

    doc = mongo_db[RUNS].find_one({"_id": ObjectId(run["id"])})
    assert doc is not None and doc["status"] == "queued"
    assert job_status(settings, run["id"]) == JobStatus.queued
    auths = {request.headers.get("authorization") for request in fake_records.requests}
    assert auths == {f"Bearer {token}"}


def test_snapshot_is_immutable(
    client: TestClient,
    fake_records: Any,
    settings: Settings,
    mongo_db: Database[dict[str, Any]],
    token: str,
) -> None:
    seed_fake_records(fake_records)
    seed_rows(settings)
    run = client.post(RUNS_URL, json=run_body(), headers=_bearer(token)).json()
    before = client.get(f"{RUNS_URL}/{run['id']}", headers=_bearer(token)).json()["snapshot"]
    delete_redis_keys(settings, f"arq:job:{run_job_id(run['id'])}")

    fake_records.generic_bodies["models"][1]["model_name"] = "renamed"
    fake_records.generic_bodies["providers"][1]["name"] = "changed"
    fake_records.generic_bodies["scorers"][1]["kind"] = "contains"
    fake_records.add(
        "prompt-versions",
        2,
        {
            "id": 2,
            "template": 1,
            "system_message": "newer",
            "body": "new body",
            "number": 2,
            "variables": [],
        },
    )
    after = client.get(f"{RUNS_URL}/{run['id']}", headers=_bearer(token)).json()["snapshot"]
    assert after == before


def test_create_run_no_token(client: TestClient, fake_records: Any) -> None:
    assert client.post(RUNS_URL, json=run_body()).status_code == 401
    assert fake_records.requests == []


def assert_no_run_no_job(settings: Settings, mongo_db: Database[dict[str, Any]]) -> None:
    assert mongo_db[RUNS].count_documents({}) == 0


@pytest.mark.parametrize(
    ("mutate", "expected_status"),
    [
        (lambda fake, s: s.update(viewer=True), 403),
        (lambda fake, s: fake.generic_bodies["projects"].pop(1), 400),
        (
            lambda fake, s: fake.add("prompt-templates", 1, {"id": 1, "project": 9, "name": "t"}),
            400,
        ),
        (lambda fake, s: fake.add_dataset(7, organization=ORG, project=9, row_count=2), 400),
        (lambda fake, s: fake.add_dataset(7, organization=ORG, project=1, row_count=None), 400),
        (
            lambda fake, s: fake.generic_bodies["providers"][1].update({"organization": 99}),
            400,
        ),
        (
            lambda fake, s: fake.generic_bodies["providers"][1].update({"kind": "ollama"}),
            400,
        ),
        (
            lambda fake, s: fake.generic_bodies["scorers"][1].update({"kind": "llm_judge"}),
            400,
        ),
        (
            lambda fake, s: fake.add(
                "scorers", 1, {"id": 1, "project": 9, "name": "s", "kind": "exact", "params": {}}
            ),
            400,
        ),
    ],
    ids=[
        "viewer",
        "project-404",
        "version-other-project",
        "dataset-other-project",
        "dataset-no-rows",
        "provider-other-org",
        "ollama-provider",
        "llm-judge",
        "scorer-other-project",
    ],
)
def test_create_run_rejections(
    client: TestClient,
    fake_records: Any,
    settings: Settings,
    mongo_db: Database[dict[str, Any]],
    token: str,
    viewer_token: str,
    mutate: Any,
    expected_status: int,
) -> None:
    seed_fake_records(fake_records)
    seed_rows(settings)
    marker: dict[str, bool] = {}
    mutate(fake_records, marker)
    headers = _bearer(viewer_token if marker.get("viewer") else token)
    response = client.post(RUNS_URL, json=run_body(), headers=headers)
    assert response.status_code == expected_status, response.text
    assert_no_run_no_job(settings, mongo_db)


def test_create_run_missing_variables(
    client: TestClient,
    fake_records: Any,
    settings: Settings,
    mongo_db: Database[dict[str, Any]],
    token: str,
) -> None:
    seed_fake_records(fake_records)
    seed_rows(settings, with_question=False)
    response = client.post(RUNS_URL, json=run_body(), headers=_bearer(token))
    assert response.status_code == 400
    detail = response.json()["detail"]
    assert "question" in detail and "rows 0" in detail
    assert_no_run_no_job(settings, mongo_db)


def test_create_run_duplicate_models_422(
    client: TestClient,
    fake_records: Any,
    settings: Settings,
    mongo_db: Database[dict[str, Any]],
    token: str,
) -> None:
    response = client.post(RUNS_URL, json=run_body(model_config_ids=[1, 1]), headers=_bearer(token))
    assert response.status_code == 422
    assert_no_run_no_job(settings, mongo_db)


def test_create_run_empty_models_422(
    client: TestClient,
    fake_records: Any,
    settings: Settings,
    mongo_db: Database[dict[str, Any]],
    token: str,
) -> None:
    response = client.post(RUNS_URL, json=run_body(model_config_ids=[]), headers=_bearer(token))
    assert response.status_code == 422
    assert_no_run_no_job(settings, mongo_db)


def test_create_run_records_connect_error_502(
    client: TestClient,
    fake_records: Any,
    settings: Settings,
    mongo_db: Database[dict[str, Any]],
    token: str,
) -> None:
    fake_records.connect_error = True
    response = client.post(RUNS_URL, json=run_body(), headers=_bearer(token))
    assert response.status_code == 502
    assert response.json()["detail"] == "Records service unavailable"
    assert_no_run_no_job(settings, mongo_db)


def test_create_run_enqueue_failure_502(
    client: TestClient,
    fake_records: Any,
    settings: Settings,
    mongo_db: Database[dict[str, Any]],
    token: str,
) -> None:
    seed_fake_records(fake_records)
    seed_rows(settings)
    dead = ArqRedis(connection_pool=ConnectionPool.from_url("redis://127.0.0.1:6390/0"))
    original = cast(FastAPI, client.app).state.redis
    cast(FastAPI, client.app).state.redis = dead
    try:
        response = client.post(RUNS_URL, json=run_body(), headers=_bearer(token))
        assert response.status_code == 502
        assert response.json()["detail"] == "Job queue unavailable"
        assert_no_run_no_job(settings, mongo_db)
    finally:
        cast(FastAPI, client.app).state.redis = original
        asyncio.run(dead.aclose())


def test_list_runs_paging_and_org_scope(
    client: TestClient,
    settings: Settings,
    mongo_db: Database[dict[str, Any]],
    token: str,
    viewer_token: str,
) -> None:
    ids = [
        insert_run_doc(
            mongo_db,
            created_at=datetime(2026, 11, day, tzinfo=UTC),
        )
        for day in (1, 2, 3)
    ]
    insert_run_doc(mongo_db, org=99)
    first = client.get(
        RUNS_URL, params={"project_id": 1, "limit": 2}, headers=_bearer(viewer_token)
    )
    assert first.status_code == 200
    page = first.json()
    assert [r["id"] for r in page["items"]] == ids[::-1][:2]
    assert page["next_before"] == ids[1]
    second = client.get(
        RUNS_URL,
        params={"project_id": 1, "limit": 2, "before": page["next_before"]},
        headers=_bearer(token),
    )
    assert second.status_code == 200
    assert [r["id"] for r in second.json()["items"]] == ids[::-1][2:]
    assert second.json()["next_before"] is None


def test_list_runs_requires_project_id(client: TestClient, token: str) -> None:
    assert client.get(RUNS_URL, headers=_bearer(token)).status_code == 422
    assert (
        client.get(
            RUNS_URL, params={"project_id": 1, "limit": 101}, headers=_bearer(token)
        ).status_code
        == 422
    )


def test_get_run_detail(
    client: TestClient,
    mongo_db: Database[dict[str, Any]],
    token: str,
    viewer_token: str,
) -> None:
    run_id = insert_run_doc(mongo_db)
    response = client.get(f"{RUNS_URL}/{run_id}", headers=_bearer(viewer_token))
    assert response.status_code == 200 and response.json()["id"] == run_id
    other = insert_run_doc(mongo_db, org=99)
    assert client.get(f"{RUNS_URL}/{other}", headers=_bearer(token)).status_code == 404
    assert client.get(f"{RUNS_URL}/not-hex", headers=_bearer(token)).status_code == 404


def seed_results(mongo_db: Database[dict[str, Any]], run_id: str) -> None:
    mongo_db[RESULTS].insert_many(
        [
            {
                "run_id": ObjectId(run_id),
                "model_config_id": 1,
                "row_index": 0,
                "input": {"q": "a"},
                "expected": "e",
                "rendered_prompt": "p",
                "output": "o",
                "usage": {"input_tokens": 1, "output_tokens": 1},
                "latency_ms": 5,
                "cost_usd": 0.0,
                "error": None,
                "context_limited": False,
                "scores": [{"scorer_id": 1, "value": 0.5}],
            },
            {
                "run_id": ObjectId(run_id),
                "model_config_id": 1,
                "row_index": 1,
                "input": {"q": "b"},
                "expected": "e",
                "rendered_prompt": "p",
                "output": "o",
                "usage": {"input_tokens": 1, "output_tokens": 1},
                "latency_ms": 5,
                "cost_usd": 0.0,
                "error": "boom",
                "context_limited": False,
                "scores": [{"scorer_id": 1, "value": 0.1}],
            },
            {
                "run_id": ObjectId(run_id),
                "model_config_id": 2,
                "row_index": 0,
                "input": {"q": "c"},
                "expected": None,
                "rendered_prompt": "p",
                "output": "o",
                "usage": {"input_tokens": 1, "output_tokens": 1},
                "latency_ms": 5,
                "cost_usd": 0.0,
                "error": None,
                "context_limited": False,
                "scores": [{"scorer_id": 1, "value": None}],
            },
        ]
    )


def test_results_paging_and_filters(
    client: TestClient,
    mongo_db: Database[dict[str, Any]],
    token: str,
) -> None:
    run_id = insert_run_doc(mongo_db)
    seed_results(mongo_db, run_id)
    url = f"{RUNS_URL}/{run_id}/results"

    page = client.get(url, params={"limit": 2}, headers=_bearer(token)).json()
    assert [(r["model_config_id"], r["row_index"]) for r in page["items"]] == [
        (1, 0),
        (1, 1),
    ]
    assert page["next_after"] == "1:1"
    page2 = client.get(
        url, params={"limit": 2, "after": page["next_after"]}, headers=_bearer(token)
    ).json()
    assert [(r["model_config_id"], r["row_index"]) for r in page2["items"]] == [(2, 0)]
    assert page2["next_after"] is None

    errors = client.get(url, params={"errors_only": True}, headers=_bearer(token)).json()
    assert [(r["model_config_id"], r["row_index"]) for r in errors["items"]] == [(1, 1)]
    low = client.get(url, params={"scorer_id": 1, "max_score": 0.4}, headers=_bearer(token)).json()
    assert [(r["model_config_id"], r["row_index"]) for r in low["items"]] == [(1, 1)]
    by_model = client.get(url, params={"model_config_id": 2}, headers=_bearer(token)).json()
    assert len(by_model["items"]) == 1

    assert client.get(url, params={"after": "bad"}, headers=_bearer(token)).status_code == 422
    other = insert_run_doc(mongo_db, org=99)
    assert client.get(f"{RUNS_URL}/{other}/results", headers=_bearer(token)).status_code == 404


def test_cancel_queued_run(
    client: TestClient,
    settings: Settings,
    mongo_db: Database[dict[str, Any]],
    token: str,
) -> None:
    run_id = insert_run_doc(mongo_db)
    response = client.post(f"{RUNS_URL}/{run_id}/cancel", headers=_bearer(token))
    assert response.status_code == 200
    run = response.json()
    assert run["status"] == "cancelled" and run["finished_at"] is not None
    assert redis_keys_exist(settings, cancel_key(run_id))
    delete_redis_keys(settings, cancel_key(run_id))


def test_cancel_running_run_flags_only(
    client: TestClient,
    settings: Settings,
    mongo_db: Database[dict[str, Any]],
    token: str,
) -> None:
    run_id = insert_run_doc(mongo_db, status="running")
    response = client.post(f"{RUNS_URL}/{run_id}/cancel", headers=_bearer(token))
    assert response.status_code == 200 and response.json()["status"] == "running"
    assert redis_keys_exist(settings, cancel_key(run_id))
    delete_redis_keys(settings, cancel_key(run_id))


def test_cancel_running_run_dead_redis_502(
    client: TestClient,
    mongo_db: Database[dict[str, Any]],
    token: str,
) -> None:
    run_id = insert_run_doc(mongo_db, status="running")
    dead = ArqRedis(connection_pool=ConnectionPool.from_url("redis://127.0.0.1:6390/0"))
    original = cast(FastAPI, client.app).state.redis
    cast(FastAPI, client.app).state.redis = dead
    try:
        response = client.post(f"{RUNS_URL}/{run_id}/cancel", headers=_bearer(token))
        assert response.status_code == 502
    finally:
        cast(FastAPI, client.app).state.redis = original
        asyncio.run(dead.aclose())


def test_cancel_finished_run_409(
    client: TestClient, mongo_db: Database[dict[str, Any]], token: str
) -> None:
    run_id = insert_run_doc(mongo_db, status="finished")
    response = client.post(f"{RUNS_URL}/{run_id}/cancel", headers=_bearer(token))
    assert response.status_code == 409


def test_cancel_viewer_403_other_org_404(
    client: TestClient,
    mongo_db: Database[dict[str, Any]],
    token: str,
    viewer_token: str,
) -> None:
    run_id = insert_run_doc(mongo_db)
    assert (
        client.post(f"{RUNS_URL}/{run_id}/cancel", headers=_bearer(viewer_token)).status_code == 403
    )
    other = insert_run_doc(mongo_db, org=99)
    assert client.post(f"{RUNS_URL}/{other}/cancel", headers=_bearer(token)).status_code == 404
