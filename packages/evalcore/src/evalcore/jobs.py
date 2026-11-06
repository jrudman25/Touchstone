"""The single seam for enqueueing arq jobs.

arq is in maintenance-only mode upstream, so every enqueue goes through
this module to keep a later swap contained. Job ids are deterministic per
run so a duplicate enqueue is a no-op rather than a second execution.
"""

from arq import ArqRedis
from arq.connections import RedisSettings

RUN_JOB_NAME = "execute_run"


def run_job_id(run_id: str) -> str:
    return f"run:{run_id}"


def redis_settings(url: str) -> RedisSettings:
    return RedisSettings.from_dsn(url)


async def enqueue_run(redis: ArqRedis, run_id: str, *, queue_name: str | None = None) -> bool:
    """Enqueue the run job. False when the job id is already taken."""
    if queue_name is None:
        job = await redis.enqueue_job(RUN_JOB_NAME, run_id, _job_id=run_job_id(run_id))
    else:
        job = await redis.enqueue_job(
            RUN_JOB_NAME, run_id, _job_id=run_job_id(run_id), _queue_name=queue_name
        )
    return job is not None
