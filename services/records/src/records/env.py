"""Environment variable helpers for Django settings.

Reads process environment only; no dotenv dependency. Services load .env via
``uv run --env-file .env`` before starting.
"""

import os

from django.core.exceptions import ImproperlyConfigured


def require_env(name: str) -> str:
    """Return the value of a required environment variable."""
    try:
        return os.environ[name]
    except KeyError:
        raise ImproperlyConfigured(f"Missing required environment variable: {name}") from None


def env_bool(name: str, default: bool = False) -> bool:
    """Parse a boolean environment variable; accepts only true/false (any case)."""
    raw = os.environ.get(name)
    if raw is None or raw == "":
        return default
    lowered = raw.lower()
    if lowered == "true":
        return True
    if lowered == "false":
        return False
    raise ImproperlyConfigured(f"{name} must be 'true' or 'false', got {raw!r}")


def env_list(name: str, default: list[str] | None = None) -> list[str]:
    """Parse a comma-separated environment variable into a list of strings."""
    raw = os.environ.get(name)
    if raw is None:
        return list(default) if default else []
    return [item.strip() for item in raw.split(",") if item.strip()]
