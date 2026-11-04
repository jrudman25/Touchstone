"""Dataset row schema and MongoDB helpers shared by FastAPI and the worker.

``DatasetRowInput`` validates one JSONL upload line strictly: input values
keep their JSON type (``"1"`` stays a string, ``true`` stays a bool, and no
string-to-number coercion happens), NaN and Infinity are rejected, and extra
keys fail. ``DatasetRow`` is the stored-document shape.
"""

from collections.abc import Sequence
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictFloat, StrictInt, StrictStr
from pymongo import ASCENDING
from pymongo.asynchronous.database import AsyncDatabase

from evalcore.mongo import DATASET_ROWS


class DatasetRowInput(BaseModel):
    """One JSONL upload line: ``{"input": {...}, "expected": "..."}``."""

    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False)

    input: dict[str, StrictStr | StrictInt | StrictFloat | StrictBool]
    expected: str | None = None


class DatasetRow(BaseModel):
    """The stored ``dataset_rows`` document shape (no ``_id``)."""

    dataset_id: int
    row_index: int = Field(ge=0)
    input: dict[str, str | int | float | bool]
    expected: str | None


async def insert_dataset_rows(
    db: AsyncDatabase[dict[str, Any]],
    dataset_id: int,
    rows: Sequence[DatasetRowInput],
    *,
    batch_size: int = 1000,
) -> None:
    """Insert ``rows`` in ordered ``insert_many`` batches, row_index = position."""
    collection = db[DATASET_ROWS]
    for start in range(0, len(rows), batch_size):
        documents = [
            DatasetRow(
                dataset_id=dataset_id,
                row_index=index,
                input=row.input,
                expected=row.expected,
            ).model_dump()
            for index, row in enumerate(rows[start : start + batch_size], start=start)
        ]
        await collection.insert_many(documents, ordered=True)


async def delete_dataset_rows(db: AsyncDatabase[dict[str, Any]], dataset_id: int) -> int:
    """Delete every row of ``dataset_id`` and return the deleted count."""
    result = await db[DATASET_ROWS].delete_many({"dataset_id": dataset_id})
    return result.deleted_count


async def list_dataset_rows(
    db: AsyncDatabase[dict[str, Any]],
    dataset_id: int,
    *,
    after: int | None,
    limit: int,
) -> list[DatasetRow]:
    """Keyset-page rows of ``dataset_id`` by ascending ``row_index``."""
    query: dict[str, Any] = {"dataset_id": dataset_id}
    if after is not None:
        query["row_index"] = {"$gt": after}
    cursor = (
        db[DATASET_ROWS]
        .find(query, projection={"_id": 0})
        .sort("row_index", ASCENDING)
        .limit(limit)
    )
    return [DatasetRow.model_validate(document) async for document in cursor]
