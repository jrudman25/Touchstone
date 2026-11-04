"""Tests for eval_api.settings and startup behavior without configuration."""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from eval_api.main import create_app
from eval_api.settings import (
    DEFAULT_DATASET_UPLOAD_MAX_BYTES,
    DEFAULT_DATASET_UPLOAD_MAX_ROWS,
    SettingsError,
    load_settings,
)


def _environ(tmp_path: Path, **overrides: str) -> dict[str, str]:
    key_file = tmp_path / "public.pem"
    if not key_file.exists():
        key_file.write_text("PUBLIC KEY CONTENT", encoding="utf-8")
    env = {
        "JWT_PUBLIC_KEY_PATH": str(key_file),
        "MONGO_URL": "mongodb://127.0.0.1:27017",
        "MONGO_DB": "touchstone_test",
        "RECORDS_BASE_URL": "http://127.0.0.1:8000",
    }
    env.update(overrides)
    return env


def test_load_settings_missing_var() -> None:
    with pytest.raises(SettingsError, match="JWT_PUBLIC_KEY_PATH"):
        load_settings({})


def test_load_settings_empty_var() -> None:
    with pytest.raises(SettingsError, match="JWT_PUBLIC_KEY_PATH"):
        load_settings({"JWT_PUBLIC_KEY_PATH": ""})


@pytest.mark.parametrize("missing", ["MONGO_URL", "MONGO_DB", "RECORDS_BASE_URL"])
def test_load_settings_missing_required_var(tmp_path: Path, missing: str) -> None:
    env = _environ(tmp_path)
    del env[missing]
    with pytest.raises(SettingsError, match=missing):
        load_settings(env)


@pytest.mark.parametrize("missing", ["MONGO_URL", "MONGO_DB", "RECORDS_BASE_URL"])
def test_load_settings_empty_required_var(tmp_path: Path, missing: str) -> None:
    env = _environ(tmp_path, **{missing: ""})
    with pytest.raises(SettingsError, match=missing):
        load_settings(env)


def test_load_settings_unreadable_file(tmp_path: Path) -> None:
    missing = tmp_path / "does-not-exist.pem"
    with pytest.raises(SettingsError, match="JWT_PUBLIC_KEY_PATH") as exc_info:
        load_settings({"JWT_PUBLIC_KEY_PATH": str(missing)})
    assert str(missing) in str(exc_info.value)


def test_load_settings_reads_file(tmp_path: Path) -> None:
    key_file = tmp_path / "public.pem"
    key_file.write_text("PUBLIC KEY CONTENT", encoding="utf-8")
    settings = load_settings(_environ(tmp_path))
    assert settings.jwt_public_key == "PUBLIC KEY CONTENT"


def test_load_settings_strips_trailing_slash(tmp_path: Path) -> None:
    settings = load_settings(_environ(tmp_path, RECORDS_BASE_URL="http://127.0.0.1:8000/"))
    assert settings.records_base_url == "http://127.0.0.1:8000"


def test_load_settings_defaults(tmp_path: Path) -> None:
    settings = load_settings(_environ(tmp_path))
    assert settings.dataset_upload_max_bytes == DEFAULT_DATASET_UPLOAD_MAX_BYTES
    assert settings.dataset_upload_max_rows == DEFAULT_DATASET_UPLOAD_MAX_ROWS


def test_load_settings_custom_limits(tmp_path: Path) -> None:
    settings = load_settings(
        _environ(tmp_path, DATASET_UPLOAD_MAX_BYTES="1024", DATASET_UPLOAD_MAX_ROWS="9")
    )
    assert settings.dataset_upload_max_bytes == 1024
    assert settings.dataset_upload_max_rows == 9


@pytest.mark.parametrize("name", ["DATASET_UPLOAD_MAX_BYTES", "DATASET_UPLOAD_MAX_ROWS"])
@pytest.mark.parametrize("bad", ["abc", "0", "-5"])
def test_load_settings_invalid_limits(tmp_path: Path, name: str, bad: str) -> None:
    with pytest.raises(SettingsError, match=name):
        load_settings(_environ(tmp_path, **{name: bad}))


def test_create_app_fails_at_startup_without_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("JWT_PUBLIC_KEY_PATH", raising=False)
    with pytest.raises(SettingsError), TestClient(create_app()):
        pass


def test_openapi_without_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("JWT_PUBLIC_KEY_PATH", raising=False)
    schema = create_app().openapi()
    assert "/health" in schema["paths"]
    assert "/api/eval/me" in schema["paths"]
