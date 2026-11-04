"""Dataset authorization dependency.

Dataset endpoints authorize by fetching the dataset from Django with the
caller's own JWT: the token is verified first (401 before any Django call),
the fetch's status is mapped through, then the caller's role on the
dataset's organization is checked against the minimum.
"""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials

from eval_api.auth import bearer_scheme, get_claims
from eval_api.deps import get_records_client
from eval_api.records_client import RecordsClient, RecordsDataset, RecordsError
from evalcore import AccessClaims, Role


@dataclass(frozen=True)
class DatasetAccess:
    dataset: RecordsDataset
    claims: AccessClaims
    authorization: str


def require_dataset_role(minimum: Role) -> Callable[..., Awaitable[DatasetAccess]]:
    """Build a dependency requiring at least ``minimum`` on the dataset's org."""

    async def dependency(
        dataset_id: int,
        claims: Annotated[AccessClaims, Depends(get_claims)],
        credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)],
        records: Annotated[RecordsClient, Depends(get_records_client)],
    ) -> DatasetAccess:
        if credentials is None:  # unreachable: get_claims already required it
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Not authenticated",
                headers={"WWW-Authenticate": "Bearer"},
            )
        authorization = f"Bearer {credentials.credentials}"
        try:
            dataset = await records.get_dataset(dataset_id, authorization)
        except RecordsError as exc:
            if exc.status_code == status.HTTP_401_UNAUTHORIZED:
                raise HTTPException(
                    status_code=exc.status_code,
                    detail=exc.detail,
                    headers={"WWW-Authenticate": "Bearer"},
                ) from exc
            raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc
        if not claims.has_role(dataset.organization, minimum):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Insufficient role for this organization",
            )
        return DatasetAccess(dataset=dataset, claims=claims, authorization=authorization)

    return dependency
