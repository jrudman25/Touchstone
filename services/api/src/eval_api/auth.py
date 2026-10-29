"""Bearer-token authentication and per-organization role dependencies."""

from collections.abc import Awaitable, Callable
from typing import Annotated

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from evalcore import AccessClaims, InvalidAccessTokenError, Role, verify_access_token

bearer_scheme = HTTPBearer(auto_error=False)


def _unauthenticated(detail: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=detail,
        headers={"WWW-Authenticate": "Bearer"},
    )


async def get_claims(
    request: Request,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)],
) -> AccessClaims:
    """Verify the bearer access token and return its validated claims."""
    if credentials is None:
        raise _unauthenticated("Not authenticated")
    try:
        return verify_access_token(
            credentials.credentials, request.app.state.settings.jwt_public_key
        )
    except InvalidAccessTokenError as exc:
        raise _unauthenticated("Invalid or expired token") from exc


def require_org_role(minimum: Role) -> Callable[..., Awaitable[AccessClaims]]:
    """Build a dependency requiring at least ``minimum`` on ``organization_id``."""

    async def dependency(
        organization_id: int,
        claims: Annotated[AccessClaims, Depends(get_claims)],
    ) -> AccessClaims:
        if not claims.has_role(organization_id, minimum):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Insufficient role for this organization",
            )
        return claims

    return dependency
