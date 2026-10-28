"""Unit tests for the evalcore access-token verifier (no Django, no DB)."""

import subprocess
import sys
import time
from typing import Any

import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from evalcore import AccessClaims, InvalidAccessTokenError, Role, verify_access_token


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


def _mint(private_pem: str, claims: dict[str, Any], algorithm: str = "RS256") -> str:
    return jwt.encode(claims, private_pem, algorithm=algorithm)


def test_valid_token(rsa_keypair: tuple[str, str]) -> None:
    private, public = rsa_keypair
    claims = verify_access_token(_mint(private, _claims()), public)
    assert isinstance(claims, AccessClaims)
    assert claims.user_id == 7
    assert claims.orgs == {1: Role.OWNER, 2: Role.VIEWER}
    assert claims.exp.tzinfo is not None
    assert claims.jti == "jti-123"


def test_user_id_int_accepted(rsa_keypair: tuple[str, str]) -> None:
    private, public = rsa_keypair
    claims = verify_access_token(_mint(private, _claims(user_id=7)), public)
    assert claims.user_id == 7


def test_role_ranking(rsa_keypair: tuple[str, str]) -> None:
    private, public = rsa_keypair
    claims = verify_access_token(_mint(private, _claims()), public)
    assert claims.role_in(1) == Role.OWNER
    assert claims.role_in(2) == Role.VIEWER
    assert claims.role_in(99) is None
    assert claims.has_role(1, Role.OWNER)
    assert claims.has_role(1, Role.EDITOR)
    assert claims.has_role(1, Role.VIEWER)
    assert not claims.has_role(2, Role.EDITOR)
    assert claims.has_role(2, Role.VIEWER)
    assert not claims.has_role(99, Role.VIEWER)


def _reject(rsa_keypair: tuple[str, str], **overrides: Any) -> None:
    private, public = rsa_keypair
    token = _mint(private, _claims(**overrides))
    with pytest.raises(InvalidAccessTokenError):
        verify_access_token(token, public)


def test_missing_exp_rejected(rsa_keypair: tuple[str, str]) -> None:
    private, public = rsa_keypair
    claims = _claims()
    del claims["exp"]
    with pytest.raises(InvalidAccessTokenError):
        verify_access_token(_mint(private, claims), public)


def test_expired_rejected(rsa_keypair: tuple[str, str]) -> None:
    _reject(rsa_keypair, exp=int(time.time()) - 10)


def test_expired_within_leeway_accepted(rsa_keypair: tuple[str, str]) -> None:
    private, public = rsa_keypair
    token = _mint(private, _claims(exp=int(time.time()) - 5))
    claims = verify_access_token(token, public, leeway_seconds=10)
    assert claims.user_id == 7


def test_missing_token_type_rejected(rsa_keypair: tuple[str, str]) -> None:
    private, public = rsa_keypair
    claims = _claims()
    del claims["token_type"]
    with pytest.raises(InvalidAccessTokenError):
        verify_access_token(_mint(private, claims), public)


def test_refresh_token_type_rejected(rsa_keypair: tuple[str, str]) -> None:
    _reject(rsa_keypair, token_type="refresh")


def test_missing_user_id_rejected(rsa_keypair: tuple[str, str]) -> None:
    private, public = rsa_keypair
    claims = _claims()
    del claims["user_id"]
    with pytest.raises(InvalidAccessTokenError):
        verify_access_token(_mint(private, claims), public)


@pytest.mark.parametrize("bad_id", [True, "abc", 0, -1, "1.5", 2.5, None])
def test_bad_user_id_rejected(rsa_keypair: tuple[str, str], bad_id: object) -> None:
    _reject(rsa_keypair, user_id=bad_id)


def test_missing_jti_rejected(rsa_keypair: tuple[str, str]) -> None:
    private, public = rsa_keypair
    claims = _claims()
    del claims["jti"]
    with pytest.raises(InvalidAccessTokenError):
        verify_access_token(_mint(private, claims), public)


def test_missing_orgs_rejected(rsa_keypair: tuple[str, str]) -> None:
    private, public = rsa_keypair
    claims = _claims()
    del claims["orgs"]
    with pytest.raises(InvalidAccessTokenError):
        verify_access_token(_mint(private, claims), public)


@pytest.mark.parametrize("bad_orgs", ["viewer", [1, 2], 5, None])
def test_orgs_not_object_rejected(rsa_keypair: tuple[str, str], bad_orgs: object) -> None:
    _reject(rsa_keypair, orgs=bad_orgs)


@pytest.mark.parametrize("bad_key", ["x", "-1", "1.5", "", " 3"])
def test_orgs_bad_key_rejected(rsa_keypair: tuple[str, str], bad_key: str) -> None:
    _reject(rsa_keypair, orgs={bad_key: "viewer"})


def test_orgs_unknown_role_rejected(rsa_keypair: tuple[str, str]) -> None:
    _reject(rsa_keypair, orgs={"1": "superuser"})


def test_wrong_signing_key_rejected(rsa_keypair: tuple[str, str]) -> None:
    private, _public = rsa_keypair
    other_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    other_public = (
        other_key.public_key()
        .public_bytes(
            serialization.Encoding.PEM,
            serialization.PublicFormat.SubjectPublicKeyInfo,
        )
        .decode()
    )
    token = _mint(private, _claims())
    with pytest.raises(InvalidAccessTokenError):
        verify_access_token(token, other_public)


def test_rs512_rejected(rsa_keypair: tuple[str, str]) -> None:
    private, public = rsa_keypair
    token = _mint(private, _claims(), algorithm="RS512")
    with pytest.raises(InvalidAccessTokenError):
        verify_access_token(token, public)


def test_hs256_rejected(rsa_keypair: tuple[str, str]) -> None:
    _, public = rsa_keypair
    token = jwt.encode(_claims(), "a" * 64, algorithm="HS256")
    with pytest.raises(InvalidAccessTokenError):
        verify_access_token(token, public)


def test_unsigned_alg_none_rejected(rsa_keypair: tuple[str, str]) -> None:
    _, public = rsa_keypair
    token = jwt.encode(_claims(), "", algorithm="none")
    with pytest.raises(InvalidAccessTokenError):
        verify_access_token(token, public)


def test_tampered_payload_rejected(rsa_keypair: tuple[str, str]) -> None:
    private, public = rsa_keypair
    token = _mint(private, _claims())
    head, payload_b64, sig = token.split(".")
    import base64

    padded = payload_b64 + "=" * (-len(payload_b64) % 4)
    decoded = base64.urlsafe_b64decode(padded).decode()
    tampered = decoded.replace('"owner"', '"viewer"', 1)
    new_payload = base64.urlsafe_b64encode(tampered.encode()).rstrip(b"=").decode()
    forged = f"{head}.{new_payload}.{sig}"
    with pytest.raises(InvalidAccessTokenError):
        verify_access_token(forged, public)


def test_garbage_token_rejected(rsa_keypair: tuple[str, str]) -> None:
    _, public = rsa_keypair
    with pytest.raises(InvalidAccessTokenError):
        verify_access_token("not-a-jwt", public)


def test_evalcore_does_not_import_django() -> None:
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "import sys, evalcore.access_tokens; assert 'django' not in sys.modules",
        ],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, result.stderr
