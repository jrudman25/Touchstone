"""Environment settings for the eval-api service.

Reads configuration only; nothing here loads dotenv or touches the JWT
private key. Importing this module never reads the environment, so it is
safe under mypy and in schema-export scripts without a .env file.
"""

import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    jwt_public_key: str


class SettingsError(RuntimeError):
    """Raised when required service configuration is missing or unreadable."""


def load_settings(environ: Mapping[str, str] = os.environ) -> Settings:
    """Load settings from the environment. Relative paths resolve against CWD."""
    key_path = environ.get("JWT_PUBLIC_KEY_PATH")
    if not key_path:
        raise SettingsError("JWT_PUBLIC_KEY_PATH is not set or is empty")
    try:
        key = Path(key_path).read_text(encoding="utf-8")
    except OSError as exc:
        raise SettingsError(
            f"JWT_PUBLIC_KEY_PATH points to an unreadable file: {key_path} ({exc})"
        ) from exc
    return Settings(jwt_public_key=key)
