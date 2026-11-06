"""Run endpoints: create, history, detail, results paging, and cancel."""

import logging
from datetime import UTC, datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.security import HTTPAuthorizationCredentials
from pydantic import BaseModel, Field, field_validator
from pymongo.asynchronous.database import AsyncDatabase
from redis.exceptions import RedisError

from eval_api.auth import bearer_scheme, get_claims
from eval_api.datasets import ErrorDetail
from eval_api.deps import get_mongo_db, get_records_client, get_settings
from eval_api.records_client import RecordsClient, RecordsError
from eval_api.settings import Settings
from evalcore import (
    DATASET_ROWS,
    AccessClaims,
    ModelSnapshot,
    PromptSnapshot,
    Result,
    Role,
    Run,
    RunSnapshot,
    RunStatus,
    RunTotals,
    ScorerSnapshot,
    cancel_queued_run,
    delete_run,
    enqueue_run,
    get_run,
    insert_run,
    list_results,
    list_runs,
    request_cancel,
    run_id_var,
)

logger = logging.getLogger("eval_api.runs")

router = APIRouter(prefix="/api/eval")


class CreateRunRequest(BaseModel):
    project_id: int
    prompt_version_id: int
    dataset_id: int
    model_config_ids: list[int] = Field(min_length=1)
    scorer_ids: list[int] = Field(default_factory=list)
    seed: int = 0

    @field_validator("model_config_ids", "scorer_ids")
    @classmethod
    def _unique(cls, ids: list[int]) -> list[int]:
        if len(set(ids)) != len(ids):
            raise ValueError("ids must be unique")
        return ids


class RunPage(BaseModel):
    items: list[Run]
    next_before: str | None


class ResultPage(BaseModel):
    items: list[Result]
    next_after: str | None


def _reject(status_code: int, detail: str) -> HTTPException:
    headers = (
        {"WWW-Authenticate": "Bearer"} if status_code == status.HTTP_401_UNAUTHORIZED else None
    )
    return HTTPException(status_code=status_code, detail=detail, headers=headers)


def _records_error(exc: RecordsError, not_found_label: str | None = None) -> HTTPException:
    if exc.status_code == 404 and not_found_label is not None:
        return _reject(400, f"Unknown or inaccessible {not_found_label}")
    return _reject(exc.status_code, exc.detail)


async def _get_records_or_400(coro: Any, label: str, value: int) -> Any:
    try:
        return await coro
    except RecordsError as exc:
        raise _records_error(exc, f"{label} {value}") from exc


def _bearer(credentials: HTTPAuthorizationCredentials) -> str:
    return f"Bearer {credentials.credentials}"


def _check_role(claims: AccessClaims, organization_id: int, minimum: Role) -> None:
    if not claims.has_role(organization_id, minimum):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Insufficient role for this organization")


async def _authorized_run(
    run_id: str, db: AsyncDatabase[dict[str, Any]], claims: AccessClaims
) -> Run:
    run = await get_run(db, run_id)
    if run is None or not claims.has_role(run.organization_id, Role.VIEWER):
        raise _reject(404, "Run not found")
    return run


@router.post(
    "/runs",
    status_code=status.HTTP_201_CREATED,
    response_model=Run,
    operation_id="create_run",
    responses={
        400: {"model": ErrorDetail},
        401: {"model": ErrorDetail},
        403: {"model": ErrorDetail},
        502: {"model": ErrorDetail},
    },
)
async def create_run(
    body: CreateRunRequest,
    request: Request,
    claims: Annotated[AccessClaims, Depends(get_claims)],
    credentials: Annotated[HTTPAuthorizationCredentials, Depends(bearer_scheme)],
    db: Annotated[AsyncDatabase[dict[str, Any]], Depends(get_mongo_db)],
    records: Annotated[RecordsClient, Depends(get_records_client)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> Run:
    """Validate referenced records against Django, snapshot, insert, enqueue."""
    if credentials is None:  # unreachable: get_claims already required it
        raise _reject(401, "Not authenticated")
    auth = _bearer(credentials)

    async def get(coro: Any, label: str, value: int) -> Any:
        return await _get_records_or_400(coro, label, value)

    project = await get(records.get_project(body.project_id, auth), "project", body.project_id)
    _check_role(claims, project.organization, Role.EDITOR)
    version = await get(
        records.get_prompt_version(body.prompt_version_id, auth),
        "prompt_version",
        body.prompt_version_id,
    )
    template = await get(
        records.get_prompt_template(version.template, auth), "template", version.template
    )
    if template.project != body.project_id:
        raise _reject(400, f"Unknown or inaccessible prompt_version {body.prompt_version_id}")
    dataset = await get(records.get_dataset(body.dataset_id, auth), "dataset", body.dataset_id)
    if dataset.project != body.project_id:
        raise _reject(400, f"Unknown or inaccessible dataset {body.dataset_id}")
    if dataset.row_count is None:
        raise _reject(400, "Dataset has no rows")

    providers: dict[int, Any] = {}
    models: list[ModelSnapshot] = []
    for model_id in body.model_config_ids:
        model = await get(records.get_model_config(model_id, auth), "model", model_id)
        provider = providers.get(model.provider)
        if provider is None:
            provider = await get(
                records.get_provider(model.provider, auth), "provider", model.provider
            )
            providers[model.provider] = provider
        if provider.organization != project.organization:
            raise _reject(400, f"Unknown or inaccessible model {model_id}")
        if provider.kind != "mock":
            raise _reject(400, f"Provider kind {provider.kind} is not supported yet")
        models.append(
            ModelSnapshot(
                model_config_id=model.id,
                provider_id=provider.id,
                provider_name=provider.name,
                provider_kind="mock",
                model_name=model.model_name,
                temperature=model.temperature,
                max_tokens=model.max_tokens,
                context_length=model.context_length,
                input_price_per_1k=float(model.input_price_per_1k),
                output_price_per_1k=float(model.output_price_per_1k),
                max_concurrency=provider.max_concurrency,
                requests_per_minute=provider.requests_per_minute,
                base_url=provider.base_url,
                api_key_env=provider.api_key_env,
                digest=None,
            )
        )

    scorers: list[ScorerSnapshot] = []
    for scorer_id in body.scorer_ids:
        scorer = await get(records.get_scorer(scorer_id, auth), "scorer", scorer_id)
        if scorer.project != body.project_id:
            raise _reject(400, f"Unknown or inaccessible scorer {scorer_id}")
        if scorer.kind == "llm_judge":
            raise _reject(400, "llm_judge scorers are not supported yet")
        scorers.append(
            ScorerSnapshot(
                scorer_id=scorer.id, name=scorer.name, kind=scorer.kind, params=scorer.params
            )
        )

    if version.variables:
        missing_query: dict[str, Any] = {
            "dataset_id": body.dataset_id,
            "$or": [{f"input.{name}": {"$exists": False}} for name in version.variables],
        }
        cursor = (
            db[DATASET_ROWS].find(missing_query, {"row_index": 1}).sort("row_index", 1).limit(5)
        )
        missing_docs = [doc async for doc in cursor]
        if missing_docs:
            per_variable: dict[str, list[int]] = {}
            for doc in missing_docs:
                for name in version.variables:
                    if name not in doc.get("input", {}):
                        per_variable.setdefault(name, []).append(doc["row_index"])
            parts = ", ".join(
                f"{name} (rows {', '.join(str(i) for i in indexes)})"
                for name, indexes in per_variable.items()
            )
            raise _reject(400, f"Dataset rows are missing prompt variables: {parts}")

    run = await insert_run(
        db,
        {
            "organization_id": project.organization,
            "project_id": body.project_id,
            "prompt_version_id": body.prompt_version_id,
            "dataset_id": body.dataset_id,
            "model_config_ids": body.model_config_ids,
            "scorer_ids": body.scorer_ids,
            "snapshot": RunSnapshot(
                prompt=PromptSnapshot(
                    prompt_version_id=version.id,
                    template_id=template.id,
                    number=version.number,
                    system_message=version.system_message,
                    body=version.body,
                    variables=version.variables,
                ),
                models=models,
                scorers=scorers,
                seed=body.seed,
            ).model_dump(),
            "status": RunStatus.QUEUED.value,
            "created_by": claims.user_id,
            "created_at": datetime.now(UTC),
            "finished_at": None,
            "totals": RunTotals(
                rows=dataset.row_count * len(models), done=0, failed=0
            ).model_dump(),
            "summary": {},
            "error": None,
        },
    )
    token = run_id_var.set(run.id)
    try:
        redis = request.app.state.redis
        enqueued = redis is not None and await enqueue_run(
            redis, run.id, queue_name=settings.run_queue_name
        )
        if not enqueued:
            await delete_run(db, run.id)
            logger.warning("run not created: enqueue failed or redis unavailable")
            raise _reject(502, "Job queue unavailable")
    except HTTPException:
        raise
    except Exception:
        await delete_run(db, run.id)
        logger.exception("run not created: enqueue raised")
        raise _reject(502, "Job queue unavailable") from None
    finally:
        run_id_var.reset(token)
    logger.info(
        "run created: dataset %s models %s scorer(s) %s",
        body.dataset_id,
        body.model_config_ids,
        body.scorer_ids,
    )
    return run


@router.get(
    "/runs",
    response_model=RunPage,
    operation_id="list_runs",
    responses={401: {"model": ErrorDetail}},
)
async def get_runs(
    claims: Annotated[AccessClaims, Depends(get_claims)],
    db: Annotated[AsyncDatabase[dict[str, Any]], Depends(get_mongo_db)],
    project_id: Annotated[int, Query()],
    before: Annotated[str | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
) -> RunPage:
    """Newest-first run history for projects in the caller's organizations."""
    organization_ids = [org_id for org_id, role in claims.orgs.items()]
    runs, next_before = await list_runs(
        db,
        project_id=project_id,
        organization_ids=organization_ids,
        before=before,
        limit=limit,
    )
    return RunPage(items=runs, next_before=next_before)


@router.get(
    "/runs/{run_id}",
    response_model=Run,
    operation_id="get_run",
    responses={
        401: {"model": ErrorDetail},
        403: {"model": ErrorDetail},
        404: {"model": ErrorDetail},
    },
)
async def get_run_detail(
    run_id: str,
    claims: Annotated[AccessClaims, Depends(get_claims)],
    db: Annotated[AsyncDatabase[dict[str, Any]], Depends(get_mongo_db)],
) -> Run:
    return await _authorized_run(run_id, db, claims)


@router.get(
    "/runs/{run_id}/results",
    response_model=ResultPage,
    operation_id="list_run_results",
    responses={
        401: {"model": ErrorDetail},
        403: {"model": ErrorDetail},
        404: {"model": ErrorDetail},
        422: {"model": ErrorDetail},
    },
)
async def get_run_results(
    run_id: str,
    claims: Annotated[AccessClaims, Depends(get_claims)],
    db: Annotated[AsyncDatabase[dict[str, Any]], Depends(get_mongo_db)],
    model_config_id: Annotated[int | None, Query()] = None,
    scorer_id: Annotated[int | None, Query()] = None,
    max_score: Annotated[float | None, Query(ge=0, le=1)] = None,
    errors_only: Annotated[bool, Query()] = False,
    after: Annotated[str | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> ResultPage:
    """Keyset-paged results for a run, filterable."""
    await _authorized_run(run_id, db, claims)
    after_pair: tuple[int, int] | None = None
    if after is not None:
        parts = after.split(":")
        if len(parts) != 2 or not all(part.isdigit() for part in parts):
            raise _reject(422, "after must be '<model_config_id>:<row_index>'")
        after_pair = (int(parts[0]), int(parts[1]))
    results, next_after = await list_results(
        db,
        run_id,
        model_config_id=model_config_id,
        scorer_id=scorer_id,
        max_score=max_score,
        errors_only=errors_only,
        after=after_pair,
        limit=limit,
    )
    return ResultPage(
        items=results,
        next_after=f"{next_after[0]}:{next_after[1]}" if next_after is not None else None,
    )


@router.post(
    "/runs/{run_id}/cancel",
    response_model=Run,
    operation_id="cancel_run",
    responses={
        401: {"model": ErrorDetail},
        403: {"model": ErrorDetail},
        404: {"model": ErrorDetail},
        409: {"model": ErrorDetail},
    },
)
async def post_cancel_run(
    run_id: str,
    request: Request,
    claims: Annotated[AccessClaims, Depends(get_claims)],
    db: Annotated[AsyncDatabase[dict[str, Any]], Depends(get_mongo_db)],
) -> Run:
    """Cancel a queued run immediately or flag a running one."""
    run = await _authorized_run(run_id, db, claims)
    _check_role(claims, run.organization_id, Role.EDITOR)
    redis = request.app.state.redis
    cancelled = await cancel_queued_run(db, run_id, datetime.now(UTC))
    if cancelled is not None:
        try:
            await request_cancel(redis, run_id)
        except (OSError, RedisError):
            logger.warning("cancel flag write failed for queued run %s", run_id)
        return cancelled
    if run.status == RunStatus.RUNNING:
        try:
            await request_cancel(redis, run_id)
        except (OSError, RedisError) as exc:
            raise _reject(502, "Job queue unavailable") from exc
        return run
    raise _reject(409, f"Run already {run.status.value}")
