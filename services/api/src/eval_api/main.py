"""FastAPI application factory for the eval API service."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Annotated, Any

import httpx
from fastapi import APIRouter, Depends, FastAPI
from pydantic import BaseModel
from pymongo import AsyncMongoClient

from eval_api.auth import get_claims
from eval_api.datasets import router as datasets_router
from eval_api.records_client import RecordsClient
from eval_api.settings import Settings, load_settings
from evalcore import AccessClaims, Role, configure_logging, ensure_indexes


class HealthResponse(BaseModel):
    status: str


class MeResponse(BaseModel):
    user_id: int
    orgs: dict[int, Role]


def create_app(
    settings: Settings | None = None,
    *,
    records_transport: httpx.AsyncBaseTransport | None = None,
) -> FastAPI:
    """Build the application.

    The factory itself reads no environment, so ``create_app().openapi()``
    works without a .env file. When ``settings`` is None the lifespan loads
    them from the environment at startup, so a missing or unreadable JWT
    public key fails clearly as the server comes up.
    """

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        configure_logging()
        resolved = settings if settings is not None else load_settings()
        app.state.settings = resolved
        mongo_client: AsyncMongoClient[dict[str, Any]] = AsyncMongoClient(resolved.mongo_url)
        app.state.mongo_client = mongo_client
        app.state.mongo_db = mongo_client[resolved.mongo_db]
        await ensure_indexes(app.state.mongo_db)
        records_client = RecordsClient(resolved, transport=records_transport)
        app.state.records_client = records_client
        try:
            yield
        finally:
            await records_client.aclose()
            await mongo_client.close()

    app = FastAPI(title="Touchstone Eval API", version="0.1.0", lifespan=lifespan)

    @app.get("/health", response_model=HealthResponse, operation_id="health")
    async def health() -> HealthResponse:
        return HealthResponse(status="ok")

    router = APIRouter(prefix="/api/eval")

    @router.get("/me", response_model=MeResponse, operation_id="get_me")
    async def get_me(claims: Annotated[AccessClaims, Depends(get_claims)]) -> MeResponse:
        return MeResponse(user_id=claims.user_id, orgs=claims.orgs)

    app.include_router(router)
    app.include_router(datasets_router)
    return app


app = create_app()
