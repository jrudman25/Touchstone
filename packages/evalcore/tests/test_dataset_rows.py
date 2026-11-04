"""Tests for evalcore.mongo and evalcore.dataset_rows against real Mongo."""

import asyncio
from collections.abc import Callable, Coroutine, Mapping
from typing import Any

import pytest
from pydantic import ValidationError
from pymongo import AsyncMongoClient
from pymongo.asynchronous.database import AsyncDatabase
from pymongo.errors import DuplicateKeyError

from evalcore.dataset_rows import (
    DatasetRow,
    DatasetRowInput,
    delete_dataset_rows,
    insert_dataset_rows,
    list_dataset_rows,
)
from evalcore.mongo import DATASET_ROWS, RESULTS, RUNS, ensure_indexes

MongoFixture = tuple[str, str]
DbTest = Callable[[AsyncDatabase[dict[str, Any]]], Coroutine[Any, Any, Any]]


def run_in_db(mongo_database: MongoFixture, body: DbTest) -> None:
    """Drive an async test body with a client that lives inside the coroutine."""
    url, name = mongo_database

    async def main() -> None:
        client: AsyncMongoClient[dict[str, Any]] = AsyncMongoClient(url)
        try:
            await body(client[name])
        finally:
            await client.close()

    asyncio.run(main())


# --- ensure_indexes --------------------------------------------------------------


def index_keys(indexes: Mapping[str, Any]) -> dict[tuple[tuple[str, Any], ...], dict[str, Any]]:
    return {tuple(index["key"]): index for index in indexes.values()}


def test_ensure_indexes_creates_spec_indexes_and_is_idempotent(
    mongo_database: MongoFixture,
) -> None:
    async def body(db: AsyncDatabase[dict[str, Any]]) -> None:
        await ensure_indexes(db)
        await ensure_indexes(db)

        runs = index_keys(await db[RUNS].index_information())
        assert (("project_id", 1), ("created_at", -1)) in runs

        results = index_keys(await db[RESULTS].index_information())
        unique_results = results[(("run_id", 1), ("model_config_id", 1), ("row_index", 1))]
        assert unique_results["unique"] is True
        assert (("run_id", 1), ("scores.value", 1)) in results

        rows = index_keys(await db[DATASET_ROWS].index_information())
        unique_rows = rows[(("dataset_id", 1), ("row_index", 1))]
        assert unique_rows["unique"] is True

    run_in_db(mongo_database, body)


# --- insert / list / delete --------------------------------------------------------


def make_rows(count: int) -> list[DatasetRowInput]:
    return [
        DatasetRowInput.model_validate(
            {"input": {"question": f"q{index}", "n": index}, "expected": f"a{index}"}
        )
        for index in range(count)
    ]


def test_insert_and_list_round_trips_rows_in_order_across_batches(
    mongo_database: MongoFixture,
) -> None:
    dataset_id = 10_001

    async def body(db: AsyncDatabase[dict[str, Any]]) -> None:
        await ensure_indexes(db)
        await insert_dataset_rows(db, dataset_id, make_rows(5), batch_size=2)
        rows = await list_dataset_rows(db, dataset_id, after=None, limit=10)
        assert [row.row_index for row in rows] == [0, 1, 2, 3, 4]
        assert rows[0].input == {"question": "q0", "n": 0}
        assert type(rows[0].input["n"]) is int
        assert rows[4].expected == "a4"
        assert rows[0].dataset_id == dataset_id

    run_in_db(mongo_database, body)


def test_list_keyset_paging_with_after(mongo_database: MongoFixture) -> None:
    dataset_id = 10_002

    async def body(db: AsyncDatabase[dict[str, Any]]) -> None:
        await insert_dataset_rows(db, dataset_id, make_rows(5))
        first = await list_dataset_rows(db, dataset_id, after=None, limit=2)
        assert [row.row_index for row in first] == [0, 1]
        second = await list_dataset_rows(db, dataset_id, after=first[-1].row_index, limit=2)
        assert [row.row_index for row in second] == [2, 3]
        rest = await list_dataset_rows(db, dataset_id, after=second[-1].row_index, limit=2)
        assert [row.row_index for row in rest] == [4]

    run_in_db(mongo_database, body)


def test_unique_index_rejects_duplicate_dataset_id_row_index(
    mongo_database: MongoFixture,
) -> None:
    dataset_id = 10_003

    async def body(db: AsyncDatabase[dict[str, Any]]) -> None:
        await ensure_indexes(db)
        await insert_dataset_rows(db, dataset_id, make_rows(1))
        with pytest.raises(DuplicateKeyError):
            await db[DATASET_ROWS].insert_one(
                {
                    "dataset_id": dataset_id,
                    "row_index": 0,
                    "input": {"question": "dupe"},
                    "expected": None,
                }
            )

    run_in_db(mongo_database, body)


def test_delete_removes_only_that_datasets_rows(mongo_database: MongoFixture) -> None:
    async def body(db: AsyncDatabase[dict[str, Any]]) -> None:
        await insert_dataset_rows(db, 10_004, make_rows(3))
        await insert_dataset_rows(db, 10_005, make_rows(2))
        assert await delete_dataset_rows(db, 10_004) == 3
        assert await list_dataset_rows(db, 10_004, after=None, limit=10) == []
        remaining = await list_dataset_rows(db, 10_005, after=None, limit=10)
        assert [row.row_index for row in remaining] == [0, 1]

    run_in_db(mongo_database, body)


def test_list_dataset_rows_validates_stored_shape(mongo_database: MongoFixture) -> None:
    """list_dataset_rows returns DatasetRow models (the API response item)."""
    dataset_id = 10_006

    async def body(db: AsyncDatabase[dict[str, Any]]) -> None:
        await db[DATASET_ROWS].insert_one(
            {
                "dataset_id": dataset_id,
                "row_index": 0,
                "input": {"flag": True, "ratio": 1.5, "label": "1"},
                "expected": None,
            }
        )
        rows = await list_dataset_rows(db, dataset_id, after=None, limit=10)
        assert rows == [
            DatasetRow(
                dataset_id=dataset_id,
                row_index=0,
                input={"flag": True, "ratio": 1.5, "label": "1"},
                expected=None,
            )
        ]
        assert "_id" not in rows[0].model_dump()

    run_in_db(mongo_database, body)


# --- DatasetRowInput validation (pure pydantic) --------------------------------------


def test_input_value_types_are_preserved() -> None:
    row = DatasetRowInput.model_validate_json(
        '{"input": {"i": 1, "f": 1.5, "b": true, "s": "1"}, "expected": "x"}'
    )
    assert type(row.input["i"]) is int
    assert type(row.input["f"]) is float
    assert type(row.input["b"]) is bool
    assert type(row.input["s"]) is str
    assert row.expected == "x"


def test_expected_is_optional() -> None:
    row = DatasetRowInput.model_validate_json('{"input": {"a": 1}}')
    assert row.expected is None


@pytest.mark.parametrize(
    "line",
    [
        '{"input": {"a": NaN}}',
        '{"input": {"a": Infinity}}',
        '{"input": {"a": -Infinity}}',
        '{"input": {"a": {"b": 1}}}',
        '{"input": {"a": [1]}}',
        '{"input": {"a": null}}',
        '{"input": {"a": "x"}, "expected": 5}',
        '{"input": {"a": 1}, "extra": 1}',
        '{"expected": "x"}',
        "[1]",
        '"x"',
        "3",
    ],
)
def test_invalid_lines_are_rejected(line: str) -> None:
    with pytest.raises(ValidationError):
        DatasetRowInput.model_validate_json(line)
