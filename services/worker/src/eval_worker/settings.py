"""Environment-only settings for the arq worker.

Importing this module reads no environment, so the arq WorkerSettings
class can be imported before ``.env`` exists; ``load_settings`` fails fast
at startup with a clear ``SettingsError`` naming the missing variable.
"""

import os
from collections.abc import Mapping
from dataclasses import dataclass

DEFAULT_JOB_TIMEOUT_SECONDS = 7200
DEFAULT_EVENTS_MAXLEN = 10_000
DEFAULT_EVENTS_TTL_SECONDS = 3600
DEFAULT_QUEUE_NAME = "arq:queue"


class SettingsError(Exception):
    """Configuration could not be loaded from the environment."""


@dataclass(frozen=True)
class Settings:
    mongo_url: str
    mongo_db: str
    redis_url: str
    run_queue_name: str = DEFAULT_QUEUE_NAME
    job_timeout_seconds: int = DEFAULT_JOB_TIMEOUT_SECONDS
    events_maxlen: int = DEFAULT_EVENTS_MAXLEN
    events_ttl_seconds: int = DEFAULT_EVENTS_TTL_SECONDS


def _required(env: Mapping[str, str], name: str) -> str:
    value = env.get(name)
    if not value:
        raise SettingsError(f"{name} environment variable is required")
    return value


def _positive_int(env: Mapping[str, str], name: str, default: int) -> int:
    raw = env.get(name)
    if raw is None or raw == "":
        return default
    try:
        value = int(raw)
    except ValueError as exc:
        raise SettingsError(f"{name} must be a positive integer") from exc
    if value <= 0:
        raise SettingsError(f"{name} must be a positive integer")
    return value


def load_settings(env: Mapping[str, str] | None = None) -> Settings:
    environ = os.environ if env is None else env
    return Settings(
        mongo_url=_required(environ, "MONGO_URL"),
        mongo_db=_required(environ, "MONGO_DB"),
        redis_url=_required(environ, "REDIS_URL"),
        run_queue_name=environ.get("RUN_QUEUE_NAME") or DEFAULT_QUEUE_NAME,
        job_timeout_seconds=_positive_int(
            environ, "WORKER_JOB_TIMEOUT_SECONDS", DEFAULT_JOB_TIMEOUT_SECONDS
        ),
        events_maxlen=_positive_int(environ, "RUN_EVENTS_MAXLEN", DEFAULT_EVENTS_MAXLEN),
        events_ttl_seconds=_positive_int(
            environ, "RUN_EVENTS_TTL_SECONDS", DEFAULT_EVENTS_TTL_SECONDS
        ),
    )
