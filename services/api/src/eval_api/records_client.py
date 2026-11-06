"""Async client for the records (Django) service.

FastAPI reaches Django at ``settings.records_base_url`` and forwards the
caller's own ``Authorization`` header verbatim; no other credential ever
crosses this boundary. Every failure maps to ``RecordsError``: Django's
401/403/404/409 pass through with their ``detail`` string, and anything else
(unexpected status, unparseable body, transport error) becomes 502.
"""

import logging
from decimal import Decimal
from typing import Any, TypeVar

import httpx
from pydantic import BaseModel, ConfigDict

from eval_api.settings import Settings

logger = logging.getLogger("eval_api.records_client")

_GENERIC_DETAIL = {
    401: "Records service rejected the access token",
    403: "Records service denied access",
    404: "Not found",
    409: "Request conflicts with the current state",
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


class RecordsProject(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: int
    organization: int
    name: str


class RecordsPromptVersion(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: int
    template: int
    system_message: str
    body: str
    number: int
    variables: list[str]


class RecordsPromptTemplate(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: int
    project: int
    name: str


class RecordsModelConfig(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: int
    provider: int
    model_name: str
    temperature: float
    max_tokens: int
    context_length: int
    input_price_per_1k: Decimal
    output_price_per_1k: Decimal


class RecordsProviderConfig(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: int
    organization: int
    name: str
    kind: str
    base_url: str
    api_key_env: str
    max_concurrency: int
    requests_per_minute: int | None


class RecordsScorerConfig(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: int
    project: int
    name: str
    kind: str
    params: dict[str, Any]


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


ModelT = TypeVar("ModelT", bound=BaseModel)


class RecordsClient:
    def __init__(
        self, settings: Settings, transport: httpx.AsyncBaseTransport | None = None
    ) -> None:
        self._client = httpx.AsyncClient(
            base_url=settings.records_base_url, transport=transport, timeout=10.0
        )

    async def get_dataset(self, dataset_id: int, authorization: str) -> RecordsDataset:
        return await self._request(
            "GET", f"/api/records/datasets/{dataset_id}/", authorization, RecordsDataset
        )

    async def set_dataset_row_count(
        self, dataset_id: int, row_count: int, authorization: str
    ) -> RecordsDataset:
        return await self._request(
            "POST",
            f"/api/records/datasets/{dataset_id}/set-row-count/",
            authorization,
            RecordsDataset,
            json={"row_count": row_count},
        )

    async def get_project(self, project_id: int, authorization: str) -> RecordsProject:
        return await self._request(
            "GET", f"/api/records/projects/{project_id}/", authorization, RecordsProject
        )

    async def get_prompt_version(self, version_id: int, authorization: str) -> RecordsPromptVersion:
        return await self._request(
            "GET",
            f"/api/records/prompt-versions/{version_id}/",
            authorization,
            RecordsPromptVersion,
        )

    async def get_prompt_template(
        self, template_id: int, authorization: str
    ) -> RecordsPromptTemplate:
        return await self._request(
            "GET",
            f"/api/records/prompt-templates/{template_id}/",
            authorization,
            RecordsPromptTemplate,
        )

    async def get_model_config(
        self, model_config_id: int, authorization: str
    ) -> RecordsModelConfig:
        return await self._request(
            "GET",
            f"/api/records/models/{model_config_id}/",
            authorization,
            RecordsModelConfig,
        )

    async def get_provider(self, provider_id: int, authorization: str) -> RecordsProviderConfig:
        return await self._request(
            "GET",
            f"/api/records/providers/{provider_id}/",
            authorization,
            RecordsProviderConfig,
        )

    async def get_scorer(self, scorer_id: int, authorization: str) -> RecordsScorerConfig:
        return await self._request(
            "GET",
            f"/api/records/scorers/{scorer_id}/",
            authorization,
            RecordsScorerConfig,
        )

    async def _request(
        self,
        method: str,
        path: str,
        authorization: str,
        model: type[ModelT],
        **kwargs: Any,
    ) -> ModelT:
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
            return model.model_validate(response.json())
        except ValueError as exc:
            logger.warning("Records response body violated the contract: %r", exc)
            raise RecordsError(502, UNAVAILABLE_DETAIL) from exc

    async def aclose(self) -> None:
        await self._client.aclose()
