"""Async client for the records (Django) service.

FastAPI reaches Django at ``settings.records_base_url`` and forwards the
caller's own ``Authorization`` header verbatim; no other credential ever
crosses this boundary. Every failure maps to ``RecordsError``: Django's
401/403/404/409 pass through with their ``detail`` string, and anything else
(unexpected status, unparseable body, transport error) becomes 502.
"""

import logging
from typing import Any

import httpx
from pydantic import BaseModel, ConfigDict

from eval_api.settings import Settings

logger = logging.getLogger("eval_api.records_client")

_GENERIC_DETAIL = {
    401: "Records service rejected the access token",
    403: "Records service denied access",
    404: "Dataset not found",
    409: "Dataset row_count is already set",
}
UNAVAILABLE_DETAIL = "Records service unavailable"


class RecordsDataset(BaseModel):
    """The dataset shape the DRF ``DatasetSerializer`` returns."""

    model_config = ConfigDict(extra="ignore")

    id: int
    project: int
    organization: int
    name: str
    row_count: int | None


class RecordsError(Exception):
    """A failed call to the records service, mapped to an HTTP status."""

    def __init__(self, status_code: int, detail: str) -> None:
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


def _error_detail(response: httpx.Response) -> str | None:
    try:
        body = response.json()
    except ValueError:
        return None
    if isinstance(body, dict):
        detail = body.get("detail")
        if isinstance(detail, str):
            return detail
    return None


class RecordsClient:
    def __init__(
        self, settings: Settings, transport: httpx.AsyncBaseTransport | None = None
    ) -> None:
        self._client = httpx.AsyncClient(
            base_url=settings.records_base_url, transport=transport, timeout=10.0
        )

    async def get_dataset(self, dataset_id: int, authorization: str) -> RecordsDataset:
        return await self._request("GET", f"/api/records/datasets/{dataset_id}/", authorization)

    async def set_dataset_row_count(
        self, dataset_id: int, row_count: int, authorization: str
    ) -> RecordsDataset:
        return await self._request(
            "POST",
            f"/api/records/datasets/{dataset_id}/set-row-count/",
            authorization,
            json={"row_count": row_count},
        )

    async def _request(
        self, method: str, path: str, authorization: str, **kwargs: Any
    ) -> RecordsDataset:
        try:
            response = await self._client.request(
                method, path, headers={"Authorization": authorization}, **kwargs
            )
        except httpx.HTTPError as exc:
            logger.warning("Records request failed: %r", exc)
            raise RecordsError(502, UNAVAILABLE_DETAIL) from exc
        if response.status_code in _GENERIC_DETAIL:
            detail = _error_detail(response) or _GENERIC_DETAIL[response.status_code]
            raise RecordsError(response.status_code, detail)
        if response.status_code // 100 != 2:
            logger.warning("Records request returned %s", response.status_code)
            raise RecordsError(502, UNAVAILABLE_DETAIL)
        try:
            return RecordsDataset.model_validate(response.json())
        except ValueError as exc:
            logger.warning("Records response body violated the contract: %r", exc)
            raise RecordsError(502, UNAVAILABLE_DETAIL) from exc

    async def aclose(self) -> None:
        await self._client.aclose()
