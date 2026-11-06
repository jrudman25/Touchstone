"""MongoDB persistence for runs and results.

The only place ``ObjectId`` and hex-string ids convert. An id that is not
valid hex is treated as not found everywhere it appears.
"""

from datetime import datetime
from typing import Any

from bson import ObjectId
from pymongo import ASCENDING, DESCENDING, ReturnDocument
from pymongo.asynchronous.database import AsyncDatabase

from evalcore.mongo import RESULTS, RUNS
from evalcore.runs import Result, Run, RunStatus, RunTotals


def _from_mongo(doc: dict[str, Any]) -> Run:
    doc = dict(doc)
    doc["id"] = str(doc.pop("_id"))
    return Run.model_validate(doc)


def _object_id(run_id: str) -> ObjectId | None:
    return ObjectId(run_id) if ObjectId.is_valid(run_id) else None


async def insert_run(db: AsyncDatabase[dict[str, Any]], run_fields: dict[str, Any]) -> Run:
    """Insert a run, assigning the ``_id``."""
    doc = dict(run_fields)
    doc.setdefault("_id", ObjectId())
    await db[RUNS].insert_one(doc)
    doc["id"] = str(doc.pop("_id"))
    return Run.model_validate(doc)


async def get_run(db: AsyncDatabase[dict[str, Any]], run_id: str) -> Run | None:
    oid = _object_id(run_id)
    if oid is None:
        return None
    doc = await db[RUNS].find_one({"_id": oid})
    return _from_mongo(doc) if doc is not None else None


async def delete_run(db: AsyncDatabase[dict[str, Any]], run_id: str) -> None:
    oid = _object_id(run_id)
    if oid is not None:
        await db[RUNS].delete_one({"_id": oid})


async def list_runs(
    db: AsyncDatabase[dict[str, Any]],
    *,
    project_id: int,
    organization_ids: list[int],
    before: str | None,
    limit: int,
) -> tuple[list[Run], str | None]:
    """Newest-first keyset page of runs; ``before`` is a run id cursor."""
    query: dict[str, Any] = {"organization_id": {"$in": organization_ids}}
    query["project_id"] = project_id
    if before is not None:
        cursor_run = await get_run(db, before)
        if cursor_run is None:
            return [], None
        cursor_oid = ObjectId(before)
        query["$or"] = [
            {"created_at": {"$lt": cursor_run.created_at}},
            {
                "created_at": cursor_run.created_at,
                "_id": {"$lt": cursor_oid},
            },
        ]
    cursor = (
        db[RUNS]
        .find(query)
        .sort([("created_at", DESCENDING), ("_id", DESCENDING)])
        .limit(limit + 1)
    )
    docs = [doc async for doc in cursor]
    has_more = len(docs) > limit
    runs = [_from_mongo(doc) for doc in docs[:limit]]
    next_before = runs[-1].id if has_more and runs else None
    return runs, next_before


async def cancel_queued_run(
    db: AsyncDatabase[dict[str, Any]], run_id: str, now: datetime
) -> Run | None:
    """Atomically cancel a still-queued run; None when the run moved on."""
    oid = _object_id(run_id)
    if oid is None:
        return None
    doc = await db[RUNS].find_one_and_update(
        {"_id": oid, "status": RunStatus.QUEUED.value},
        {"$set": {"status": RunStatus.CANCELLED.value, "finished_at": now}},
        return_document=ReturnDocument.AFTER,
    )
    return _from_mongo(doc) if doc is not None else None


async def upsert_result(db: AsyncDatabase[dict[str, Any]], result_fields: dict[str, Any]) -> bool:
    """Upsert a result keyed by (run_id, model_config_id, row_index).

    Returns True when a new document was inserted (retry-safe callers use
    it to increment totals only once per result).
    """
    doc = dict(result_fields)
    run_oid = _object_id(str(doc["run_id"]))
    key = {
        "run_id": run_oid if run_oid is not None else doc["run_id"],
        "model_config_id": doc["model_config_id"],
        "row_index": doc["row_index"],
    }
    doc["run_id"] = key["run_id"]
    doc.pop("_id", None)
    outcome = await db[RESULTS].update_one(key, {"$set": doc}, upsert=True)
    return outcome.upserted_id is not None


async def existing_row_indexes(
    db: AsyncDatabase[dict[str, Any]], run_id: str, model_config_id: int
) -> set[int]:
    """Row indexes that already have a result for this run and model."""
    run_oid = _object_id(run_id)
    if run_oid is None:
        return set()
    cursor = db[RESULTS].find(
        {"run_id": run_oid, "model_config_id": model_config_id}, {"row_index": 1}
    )
    return {doc["row_index"] async for doc in cursor}


async def inc_totals(
    db: AsyncDatabase[dict[str, Any]], run_id: str, *, done: int, failed: int
) -> None:
    """Increment the stored progress counters."""
    run_oid = _object_id(run_id)
    if run_oid is None:
        return
    await db[RUNS].update_one(
        {"_id": run_oid}, {"$inc": {"totals.done": done, "totals.failed": failed}}
    )


async def mark_running(db: AsyncDatabase[dict[str, Any]], run_id: str) -> Run | None:
    """Atomically move queued -> running (also succeeds when already running)."""
    run_oid = _object_id(run_id)
    if run_oid is None:
        return None
    doc = await db[RUNS].find_one_and_update(
        {
            "_id": run_oid,
            "status": {"$in": [RunStatus.QUEUED.value, RunStatus.RUNNING.value]},
        },
        {"$set": {"status": RunStatus.RUNNING.value}},
        return_document=ReturnDocument.AFTER,
    )
    return _from_mongo(doc) if doc is not None else None


async def finalize_run(
    db: AsyncDatabase[dict[str, Any]],
    run_id: str,
    *,
    status: RunStatus,
    error: str | None,
    totals: RunTotals,
    summary: dict[str, Any],
    now: datetime,
) -> None:
    """Write the terminal status, totals, and summary in one update."""
    run_oid = _object_id(run_id)
    if run_oid is None:
        return
    await db[RUNS].update_one(
        {"_id": run_oid},
        {
            "$set": {
                "status": status.value,
                "error": error,
                "totals": totals.model_dump(),
                "summary": {k: v.model_dump() for k, v in summary.items()},
                "finished_at": now,
            }
        },
    )


async def list_running_runs(db: AsyncDatabase[dict[str, Any]]) -> list[Run]:
    """All runs still marked running (stale-job recovery scans these)."""
    cursor = db[RUNS].find({"status": RunStatus.RUNNING.value})
    return [_from_mongo(doc) async for doc in cursor]


def _result_from_mongo(doc: dict[str, Any]) -> Result:
    doc = dict(doc)
    doc["id"] = str(doc.pop("_id"))
    if isinstance(doc.get("run_id"), ObjectId):
        doc["run_id"] = str(doc["run_id"])
    return Result.model_validate(doc)


async def list_results(
    db: AsyncDatabase[dict[str, Any]],
    run_id: str,
    *,
    model_config_id: int | None = None,
    scorer_id: int | None = None,
    max_score: float | None = None,
    errors_only: bool = False,
    after: tuple[int, int] | None,
    limit: int,
) -> tuple[list[Result], tuple[int, int] | None]:
    """Keyset page of results ordered by (model_config_id, row_index)."""
    run_oid = _object_id(run_id)
    if run_oid is None:
        return [], None
    query: dict[str, Any] = {"run_id": run_oid}
    if model_config_id is not None:
        query["model_config_id"] = model_config_id
    if errors_only:
        query["error"] = {"$ne": None}
    elem: dict[str, Any] = {}
    if scorer_id is not None:
        elem["scorer_id"] = scorer_id
    if max_score is not None:
        elem["value"] = {"$lte": max_score}
    if elem:
        query["scores"] = {"$elemMatch": elem}
    if after is not None:
        after_model, after_row = after
        query["$or"] = [
            {"model_config_id": {"$gt": after_model}},
            {
                "model_config_id": after_model,
                "row_index": {"$gt": after_row},
            },
        ]
    cursor = (
        db[RESULTS]
        .find(query)
        .sort([("model_config_id", ASCENDING), ("row_index", ASCENDING)])
        .limit(limit + 1)
    )
    docs = [doc async for doc in cursor]
    has_more = len(docs) > limit
    results = [_result_from_mongo(doc) for doc in docs[:limit]]
    next_after = (
        (results[-1].model_config_id, results[-1].row_index) if has_more and results else None
    )
    return results, next_after
