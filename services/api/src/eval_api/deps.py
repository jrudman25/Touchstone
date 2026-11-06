"""Dependencies exposing the resources the lifespan puts on ``app.state``."""

from typing import Any, cast

from arq import ArqRedis
from fastapi import Request
from pymongo.asynchronous.database import AsyncDatabase

from eval_api.records_client import RecordsClient
from eval_api.settings import Settings


def get_settings(request: Request) -> Settings:
    return cast(Settings, request.app.state.settings)


def get_mongo_db(request: Request) -> AsyncDatabase[dict[str, Any]]:
    return cast(AsyncDatabase[dict[str, Any]], request.app.state.mongo_db)


def get_records_client(request: Request) -> RecordsClient:
    return cast(RecordsClient, request.app.state.records_client)


def get_redis(request: Request) -> ArqRedis:
    return cast(ArqRedis, request.app.state.redis)
