"""Environment settings for the eval-api service.

Reads configuration only; nothing here loads dotenv or touches the JWT
private key. Importing this module never reads the environment, so it is
safe under mypy and in schema-export scripts without a .env file.
"""

import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

DEFAULT_DATASET_UPLOAD_MAX_BYTES = 50 * 1024 * 1024
DEFAULT_DATASET_UPLOAD_MAX_ROWS = 100_000


@dataclass(frozen=True)
class Settings:
    jwt_public_key: str
    mongo_url: str
    mongo_db: str
    records_base_url: str
    redis_url: str
    run_queue_name: str = "arq:queue"
    dataset_upload_max_bytes: int = DEFAULT_DATASET_UPLOAD_MAX_BYTES
    dataset_upload_max_rows: int = DEFAULT_DATASET_UPLOAD_MAX_ROWS


class SettingsError(RuntimeError):
    """Raised when required service configuration is missing or unreadable."""


def _required(environ: Mapping[str, str], name: str) -> str:
    value = environ.get(name)
    if not value:
        raise SettingsError(f"{name} is not set or is empty")
    return value


def _positive_int(environ: Mapping[str, str], name: str, default: int) -> int:
    raw = environ.get(name)
    if raw is None:
        return default
    try:
        value = int(raw)
    except ValueError:
        raise SettingsError(f"{name} must be a positive integer") from None
    if value <= 0:
        raise SettingsError(f"{name} must be a positive integer")
    return value


def load_settings(environ: Mapping[str, str] = os.environ) -> Settings:
    """Load settings from the environment. Relative paths resolve against CWD."""
    key_path = _required(environ, "JWT_PUBLIC_KEY_PATH")
    try:
        key = Path(key_path).read_text(encoding="utf-8")
    except OSError as exc:
        raise SettingsError(
            f"JWT_PUBLIC_KEY_PATH points to an unreadable file: {key_path} ({exc})"
        ) from exc
    return Settings(
        jwt_public_key=key,
        mongo_url=_required(environ, "MONGO_URL"),
        mongo_db=_required(environ, "MONGO_DB"),
        records_base_url=_required(environ, "RECORDS_BASE_URL").rstrip("/"),
        redis_url=_required(environ, "REDIS_URL"),
        run_queue_name=environ.get("RUN_QUEUE_NAME") or "arq:queue",
        dataset_upload_max_bytes=_positive_int(
            environ, "DATASET_UPLOAD_MAX_BYTES", DEFAULT_DATASET_UPLOAD_MAX_BYTES
        ),
        dataset_upload_max_rows=_positive_int(
            environ, "DATASET_UPLOAD_MAX_ROWS", DEFAULT_DATASET_UPLOAD_MAX_ROWS
        ),
    )
