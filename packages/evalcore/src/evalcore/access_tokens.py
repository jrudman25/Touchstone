"""Shared access-token verifier for FastAPI and the worker.

Django is the only service that signs tokens (RS256). This module verifies
bearer access tokens with the public key and exposes the claims every
verifying service needs: user id, expiry, jti, and the {org_id: role} map.

This module must never import Django or hit a database; verification is
purely cryptographic plus claim-shape validation.
"""

from datetime import datetime
from enum import StrEnum
from typing import Any

import jwt
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator


class Role(StrEnum):
    """Organization membership roles, ordered weakest to strongest."""

    VIEWER = "viewer"
    EDITOR = "editor"
    OWNER = "owner"


_ROLE_RANK = {Role.VIEWER: 0, Role.EDITOR: 1, Role.OWNER: 2}


class InvalidAccessTokenError(Exception):
    """Raised when a bearer token fails access-token verification."""


class AccessClaims(BaseModel):
    """Validated claims of a signed access token."""

    model_config = ConfigDict(frozen=True)

    user_id: int = Field(gt=0)
    orgs: dict[int, Role]
    exp: datetime
    jti: str

    @field_validator("user_id", mode="before")
    @classmethod
    def _coerce_user_id(cls, value: Any) -> Any:
        # Django emits the user id as a JSON string; accept that or an int.
        if isinstance(value, bool):
            raise ValueError("user_id must be a positive integer")
        if isinstance(value, int):
            return value
        if isinstance(value, str) and value.isascii() and value.isdigit():
            return int(value)
        raise ValueError("user_id must be a positive integer")

    @field_validator("orgs", mode="before")
    @classmethod
    def _validate_orgs(cls, value: Any) -> Any:
        if not isinstance(value, dict):
            raise ValueError("orgs must be an object")
        # JSON object keys are strings; require ASCII digits so they convert
        # cleanly to organization ids.
        for key in value:
            if not (isinstance(key, str) and key.isascii() and key.isdigit()):
                raise ValueError("orgs keys must be ASCII-digit strings")
        return value

    def role_in(self, org_id: int) -> Role | None:
        """Return the caller's role in an organization, or None."""
        return self.orgs.get(org_id)

    def has_role(self, org_id: int, minimum: Role) -> bool:
        """True when the caller's role in the org is at least ``minimum``."""
        role = self.orgs.get(org_id)
        return role is not None and _ROLE_RANK[role] >= _ROLE_RANK[minimum]


def verify_access_token(token: str, public_key: str, *, leeway_seconds: int = 0) -> AccessClaims:
    """Verify an RS256 access token and return its validated claims.

    Rejects anything that is not a correctly signed, unexpired access token
    with a valid user_id, jti, and org role map. Errors never echo the token.
    """
    try:
        payload: dict[str, Any] = jwt.decode(
            token,
            public_key,
            algorithms=["RS256"],
            leeway=leeway_seconds,
            options={"require": ["exp", "token_type", "user_id", "jti"]},
        )
    except jwt.PyJWTError as exc:
        raise InvalidAccessTokenError(f"token verification failed: {exc}") from exc

    if payload.get("token_type") != "access":
        raise InvalidAccessTokenError("token is not an access token")

    try:
        return AccessClaims(**payload)
    except ValidationError as exc:
        raise InvalidAccessTokenError("access token has invalid claims") from exc
