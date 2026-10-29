"""HTTP tests for the eval-api app: health, /me auth, and role checks."""

import time
from collections.abc import Iterator
from typing import Annotated, Any

import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import APIRouter, Depends
from fastapi.testclient import TestClient
from httpx import Response

from eval_api.auth import require_org_role
from eval_api.main import create_app
from eval_api.settings import Settings
from evalcore import AccessClaims, Role


def _claims(**overrides: Any) -> dict[str, Any]:
    now = int(time.time())
    claims: dict[str, Any] = {
        "user_id": "7",
        "orgs": {"1": "owner", "2": "viewer"},
        "token_type": "access",
        "jti": "jti-123",
        "exp": now + 300,
        "iat": now,
    }
    claims.update(overrides)
    return claims


def _mint(private_pem: str, claims: dict[str, Any]) -> str:
    return jwt.encode(claims, private_pem, algorithm="RS256")


def _bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _assert_unauthorized(response: Response) -> None:
    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"


@pytest.fixture()
def client(rsa_keypair: tuple[str, str]) -> Iterator[TestClient]:
    _, public = rsa_keypair
    with TestClient(create_app(Settings(jwt_public_key=public))) as test_client:
        yield test_client


def test_health_no_auth(client: TestClient) -> None:
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_me_valid_token(client: TestClient, rsa_keypair: tuple[str, str]) -> None:
    private, _public = rsa_keypair
    token = _mint(private, _claims())
    response = client.get("/api/eval/me", headers=_bearer(token))
    assert response.status_code == 200
    assert response.json() == {"user_id": 7, "orgs": {"1": "owner", "2": "viewer"}}


def test_me_no_authorization_header(client: TestClient) -> None:
    _assert_unauthorized(client.get("/api/eval/me"))


def test_me_non_bearer_scheme(client: TestClient) -> None:
    _assert_unauthorized(client.get("/api/eval/me", headers={"Authorization": "Basic abc"}))


def test_me_garbage_token(client: TestClient) -> None:
    _assert_unauthorized(client.get("/api/eval/me", headers={"Authorization": "Bearer not-a-jwt"}))


def test_me_expired_token(client: TestClient, rsa_keypair: tuple[str, str]) -> None:
    private, _public = rsa_keypair
    token = _mint(private, _claims(exp=int(time.time()) - 10))
    _assert_unauthorized(client.get("/api/eval/me", headers=_bearer(token)))


def test_me_wrong_signing_key(client: TestClient) -> None:
    other_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    other_private = other_key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ).decode()
    token = _mint(other_private, _claims())
    _assert_unauthorized(client.get("/api/eval/me", headers=_bearer(token)))


def test_me_refresh_token_rejected(client: TestClient, rsa_keypair: tuple[str, str]) -> None:
    private, _public = rsa_keypair
    token = _mint(private, _claims(token_type="refresh"))
    _assert_unauthorized(client.get("/api/eval/me", headers=_bearer(token)))


@pytest.fixture()
def role_client(rsa_keypair: tuple[str, str]) -> Iterator[TestClient]:
    """App with a test-only route gated by require_org_role(Role.EDITOR)."""
    _, public = rsa_keypair
    app = create_app(Settings(jwt_public_key=public))
    router = APIRouter(prefix="/api/eval/test")

    @router.get("/orgs/{organization_id}/editor-only", operation_id="editor_only")
    async def editor_only(
        claims: Annotated[AccessClaims, Depends(require_org_role(Role.EDITOR))],
    ) -> dict[str, bool]:
        return {"ok": True}

    app.include_router(router)
    with TestClient(app) as test_client:
        yield test_client


def test_editor_role_enforced(role_client: TestClient, rsa_keypair: tuple[str, str]) -> None:
    private, _public = rsa_keypair
    token = _mint(private, _claims(orgs={"1": "viewer", "2": "editor", "3": "owner"}))
    headers = _bearer(token)
    url = "/api/eval/test/orgs/{org}/editor-only"
    assert role_client.get(url.format(org=1), headers=headers).status_code == 403
    assert role_client.get(url.format(org=2), headers=headers).status_code == 200
    assert role_client.get(url.format(org=3), headers=headers).status_code == 200
    assert role_client.get(url.format(org=99), headers=headers).status_code == 403
    assert role_client.get(url.format(org=2)).status_code == 401
