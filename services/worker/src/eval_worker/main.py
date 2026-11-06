"""arq worker entrypoint.

arq builds the worker from ``settings_cls.__dict__`` (see arq's
``get_kwargs``), so lazy attribute tricks do not work: ``queue_name``,
``redis_settings``, and ``job_timeout`` are resolved at import inside a
``try`` so the module still imports without an environment (mypy, the
OpenAPI export, and introspection never touch it). Without env vars the
attributes are simply absent and arq falls back to its own defaults, which
matches stock arq behavior.
"""

from typing import Any, ClassVar

from arq import func
from pymongo import AsyncMongoClient

from eval_worker.recovery import recover_stale_runs
from eval_worker.run_executor import execute_run
from eval_worker.settings import SettingsError, load_settings
from evalcore import RUN_JOB_NAME, configure_logging, ensure_indexes
from evalcore import redis_settings as _redis_settings


async def startup(ctx: dict[str, Any]) -> None:
    configure_logging()
    settings = load_settings()
    mongo_client: AsyncMongoClient[dict[str, Any]] = AsyncMongoClient(
        settings.mongo_url, tz_aware=True
    )
    db = mongo_client[settings.mongo_db]
    await ensure_indexes(db)
    ctx["db"] = db
    ctx["mongo_client"] = mongo_client
    ctx["settings"] = settings
    await recover_stale_runs(db, ctx["redis"], settings)


async def shutdown(ctx: dict[str, Any]) -> None:
    mongo_client = ctx.get("mongo_client")
    if mongo_client is not None:
        await mongo_client.close()


class WorkerSettings:
    functions: ClassVar = [func(execute_run, name=RUN_JOB_NAME)]
    max_jobs: ClassVar = 1
    on_startup: ClassVar = startup
    on_shutdown: ClassVar = shutdown
    allow_abort_jobs: ClassVar = True


try:
    _settings = load_settings()
except SettingsError:
    pass
else:
    WorkerSettings.queue_name = _settings.run_queue_name  # type: ignore[attr-defined]
    WorkerSettings.redis_settings = _redis_settings(  # type: ignore[attr-defined]
        _settings.redis_url
    )
    WorkerSettings.job_timeout = _settings.job_timeout_seconds  # type: ignore[attr-defined]


def get_worker_kwargs() -> dict[str, Any]:
    """WorkerSettings as a plain dict for ``create_worker``/burst tests."""
    return {
        "functions": WorkerSettings.functions,
        "max_jobs": WorkerSettings.max_jobs,
        "queue_name": WorkerSettings.queue_name,  # type: ignore[attr-defined]
        "redis_settings": WorkerSettings.redis_settings,  # type: ignore[attr-defined]
        "job_timeout": WorkerSettings.job_timeout,  # type: ignore[attr-defined]
        "on_startup": WorkerSettings.on_startup,
        "on_shutdown": WorkerSettings.on_shutdown,
        "allow_abort_jobs": WorkerSettings.allow_abort_jobs,
    }
