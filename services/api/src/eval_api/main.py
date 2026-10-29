"""FastAPI application factory for the eval API service."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Annotated

from fastapi import APIRouter, Depends, FastAPI
from pydantic import BaseModel

from eval_api.auth import get_claims
from eval_api.settings import Settings, load_settings
from evalcore import AccessClaims, Role, configure_logging


class HealthResponse(BaseModel):
    status: str


class MeResponse(BaseModel):
    user_id: int
    orgs: dict[int, Role]


def create_app(settings: Settings | None = None) -> FastAPI:
    """Build the application.

    The factory itself reads no environment, so ``create_app().openapi()``
    works without a .env file. When ``settings`` is None the lifespan loads
    them from the environment at startup, so a missing or unreadable JWT
    public key fails clearly as the server comes up.
    """

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        configure_logging()
        app.state.settings = settings if settings is not None else load_settings()
        yield

    app = FastAPI(title="Touchstone Eval API", version="0.1.0", lifespan=lifespan)

    @app.get("/health", response_model=HealthResponse, operation_id="health")
    async def health() -> HealthResponse:
        return HealthResponse(status="ok")

    router = APIRouter(prefix="/api/eval")

    @router.get("/me", response_model=MeResponse, operation_id="get_me")
    async def get_me(claims: Annotated[AccessClaims, Depends(get_claims)]) -> MeResponse:
        return MeResponse(user_id=claims.user_id, orgs=claims.orgs)

    app.include_router(router)
    return app


app = create_app()
