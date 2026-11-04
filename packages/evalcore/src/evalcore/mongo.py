"""MongoDB collection names and index creation shared by API and worker.

``ensure_indexes`` declares exactly the indexes in SPEC.md and is safe to
rerun: ``create_index`` is a no-op when an index with the same keys and
options already exists.
"""

from typing import Any

from pymongo import ASCENDING, DESCENDING
from pymongo.asynchronous.database import AsyncDatabase

RUNS = "runs"
RESULTS = "results"
DATASET_ROWS = "dataset_rows"


async def ensure_indexes(db: AsyncDatabase[dict[str, Any]]) -> None:
    """Create the SPEC.md indexes on ``db`` (idempotent)."""
    await db[RUNS].create_index([("project_id", ASCENDING), ("created_at", DESCENDING)])
    await db[RESULTS].create_index(
        [("run_id", ASCENDING), ("model_config_id", ASCENDING), ("row_index", ASCENDING)],
        unique=True,
    )
    await db[RESULTS].create_index([("run_id", ASCENDING), ("scores.value", ASCENDING)])
    await db[DATASET_ROWS].create_index(
        [("dataset_id", ASCENDING), ("row_index", ASCENDING)], unique=True
    )
