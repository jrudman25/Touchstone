"""Tests for eval_api.settings and startup behavior without configuration."""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from eval_api.main import create_app
from eval_api.settings import SettingsError, load_settings


def test_load_settings_missing_var() -> None:
    with pytest.raises(SettingsError, match="JWT_PUBLIC_KEY_PATH"):
        load_settings({})


def test_load_settings_empty_var() -> None:
    with pytest.raises(SettingsError, match="JWT_PUBLIC_KEY_PATH"):
        load_settings({"JWT_PUBLIC_KEY_PATH": ""})


def test_load_settings_unreadable_file(tmp_path: Path) -> None:
    missing = tmp_path / "does-not-exist.pem"
    with pytest.raises(SettingsError, match="JWT_PUBLIC_KEY_PATH") as exc_info:
        load_settings({"JWT_PUBLIC_KEY_PATH": str(missing)})
    assert str(missing) in str(exc_info.value)


def test_load_settings_reads_file(tmp_path: Path) -> None:
    key_file = tmp_path / "public.pem"
    key_file.write_text("PUBLIC KEY CONTENT", encoding="utf-8")
    settings = load_settings({"JWT_PUBLIC_KEY_PATH": str(key_file)})
    assert settings.jwt_public_key == "PUBLIC KEY CONTENT"


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
