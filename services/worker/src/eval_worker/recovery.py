"""Startup recovery: fail runs whose job can no longer finish.

arq keeps an in-progress key for the job timeout, so a run marked
``running`` whose job is still queued, deferred, or in progress is left
alone; anything else means the worker that held it is gone.
"""

import logging
from datetime import UTC, datetime
from typing import Any

from arq import ArqRedis
from arq.jobs import Job, JobStatus
from pymongo.asynchronous.database import AsyncDatabase

from eval_worker.run_executor import _recompute
from eval_worker.settings import Settings
from evalcore import (
    RunStatus,
    expire_events,
    finalize_run,
    list_running_runs,
    publish_event,
    run_job_id,
)

logger = logging.getLogger("eval_worker.recovery")

_ACTIVE = {JobStatus.queued, JobStatus.deferred, JobStatus.in_progress}
STALE_ERROR = "Worker stopped before the run finished"


async def recover_stale_runs(
    db: AsyncDatabase[dict[str, Any]], redis: ArqRedis, settings: Settings
) -> None:
    for run in await list_running_runs(db):
        status = await Job(run_job_id(run.id), redis, _queue_name=settings.run_queue_name).status()
        if status in _ACTIVE:
            continue
        logger.warning("marking stale running run as failed (job status %s)", status)
        totals, summary = await _recompute(db, run.id, run)
        await finalize_run(
            db,
            run.id,
            status=RunStatus.FAILED,
            error=STALE_ERROR,
            totals=totals,
            summary=summary,
            now=datetime.now(UTC),
        )
        await publish_event(
            redis,
            run.id,
            "status",
            {"status": "failed", "error": STALE_ERROR},
            maxlen=settings.events_maxlen,
        )
        await expire_events(redis, run.id, settings.events_ttl_seconds)
