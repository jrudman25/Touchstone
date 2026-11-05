"""Dataset routes: JSONL upload into MongoDB and a paged row preview."""

import logging
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from pymongo.asynchronous.database import AsyncDatabase
from pymongo.errors import BulkWriteError, PyMongoError

from eval_api.dataset_access import DatasetAccess, require_dataset_role
from eval_api.deps import get_mongo_db, get_records_client, get_settings
from eval_api.jsonl_upload import UploadLimitError, parse_jsonl_lines
from eval_api.records_client import RecordsClient, RecordsError
from eval_api.settings import Settings
from evalcore import (
    DatasetRow,
    Role,
    delete_dataset_rows,
    insert_dataset_rows,
    list_dataset_rows,
)

logger = logging.getLogger("eval_api.datasets")

router = APIRouter(prefix="/api/eval")

UPLOAD_MEDIA_TYPES = {"application/x-ndjson", "application/jsonl"}
PASSTHROUGH_STATUSES = {401, 403, 409}


class ErrorDetail(BaseModel):
    detail: str


class UploadLineError(BaseModel):
    line: int
    message: str


class UploadErrorResponse(BaseModel):
    detail: str
    errors: list[UploadLineError]


class DatasetUploadResponse(BaseModel):
    dataset_id: int
    row_count: int


class DatasetRowsPage(BaseModel):
    items: list[DatasetRow]
    next_after: int | None


def _reject(status_code: int, detail: str) -> HTTPException:
    headers = (
        {"WWW-Authenticate": "Bearer"} if status_code == status.HTTP_401_UNAUTHORIZED else None
    )
    return HTTPException(status_code=status_code, detail=detail, headers=headers)


def _upload_error(status_code: int, detail: str, errors: list[UploadLineError]) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={"detail": detail, "errors": [error.model_dump() for error in errors]},
    )


def _is_row_zero_conflict(exc: BulkWriteError) -> bool:
    """True when the first write failed on a duplicate key for row 0."""
    details = exc.details or {}
    if details.get("nInserted") != 0:
        return False
    errors = details.get("writeErrors") or []
    return len(errors) > 0 and errors[0].get("index") == 0 and errors[0].get("code") == 11000


async def _delete_dataset_rows_best_effort(
    db: AsyncDatabase[dict[str, Any]], dataset_id: int
) -> None:
    try:
        await delete_dataset_rows(db, dataset_id)
    except PyMongoError:
        logger.exception("compensation failed: could not delete dataset %s rows", dataset_id)


@router.post(
    "/datasets/{dataset_id}/rows",
    status_code=status.HTTP_201_CREATED,
    response_model=DatasetUploadResponse,
    operation_id="upload_dataset_rows",
    openapi_extra={
        "requestBody": {
            "required": True,
            "content": {
                "application/x-ndjson": {"schema": {"type": "string"}},
                "application/jsonl": {"schema": {"type": "string"}},
            },
        }
    },
    responses={
        400: {"model": UploadErrorResponse},
        401: {"model": ErrorDetail},
        403: {"model": ErrorDetail},
        404: {"model": ErrorDetail},
        409: {"model": ErrorDetail},
        413: {"model": ErrorDetail},
        415: {"model": ErrorDetail},
        502: {"model": ErrorDetail},
    },
)
async def upload_dataset_rows(
    request: Request,
    dataset_id: int,
    access: Annotated[DatasetAccess, Depends(require_dataset_role(Role.EDITOR))],
    db: Annotated[AsyncDatabase[dict[str, Any]], Depends(get_mongo_db)],
    records: Annotated[RecordsClient, Depends(get_records_client)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> DatasetUploadResponse | JSONResponse:
    """Validate a streamed JSONL upload and bulk insert it into dataset_rows."""
    if access.dataset.row_count is not None:
        logger.info("upload rejected: dataset %s rows already uploaded", dataset_id)
        raise HTTPException(status.HTTP_409_CONFLICT, "Dataset rows are already uploaded")
    media_type = request.headers.get("content-type", "").split(";")[0].strip().lower()
    if media_type not in UPLOAD_MEDIA_TYPES:
        logger.info("upload rejected: dataset %s media type %r", dataset_id, media_type)
        raise HTTPException(
            status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            "Content-Type must be application/x-ndjson or application/jsonl",
        )
    content_length = request.headers.get("content-length")
    if content_length is not None:
        try:
            declared = int(content_length)
        except ValueError:
            declared = 0
        if declared > settings.dataset_upload_max_bytes:
            logger.info("upload rejected: dataset %s over byte limit", dataset_id)
            raise HTTPException(
                status.HTTP_413_CONTENT_TOO_LARGE,
                f"Upload exceeds {settings.dataset_upload_max_bytes} bytes",
            )
    try:
        parsed = await parse_jsonl_lines(
            request.stream(),
            max_bytes=settings.dataset_upload_max_bytes,
            max_rows=settings.dataset_upload_max_rows,
        )
    except UploadLimitError as exc:
        logger.info("upload rejected: dataset %s %s", dataset_id, exc)
        raise HTTPException(status.HTTP_413_CONTENT_TOO_LARGE, str(exc)) from exc
    if parsed.line_count == 0:
        logger.info("upload rejected: dataset %s empty upload", dataset_id)
        return _upload_error(status.HTTP_400_BAD_REQUEST, "Upload is empty", [])
    if parsed.errors:
        logger.info(
            "upload rejected: dataset %s %d invalid line(s)", dataset_id, len(parsed.errors)
        )
        return _upload_error(
            status.HTTP_400_BAD_REQUEST,
            "Invalid JSONL upload",
            [UploadLineError(line=error.line, message=error.message) for error in parsed.errors],
        )
    try:
        await insert_dataset_rows(db, dataset_id, parsed.rows)
    except PyMongoError as exc:
        if isinstance(exc, BulkWriteError) and _is_row_zero_conflict(exc):
            logger.info(
                "upload rejected: dataset %s row 0 already held by another upload", dataset_id
            )
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                "Another upload for this dataset is in progress or finished",
            ) from exc
        logger.warning("upload failed: dataset %s insert error, deleting partial rows", dataset_id)
        await _delete_dataset_rows_best_effort(db, dataset_id)
        raise _reject(502, "Dataset storage unavailable") from exc
    try:
        await records.set_dataset_row_count(dataset_id, len(parsed.rows), access.authorization)
    except RecordsError as exc:
        logger.warning(
            "upload compensating: dataset %s set-row-count failed (%s), deleting rows",
            dataset_id,
            exc.status_code,
        )
        await _delete_dataset_rows_best_effort(db, dataset_id)
        if exc.status_code in PASSTHROUGH_STATUSES:
            raise _reject(exc.status_code, exc.detail) from exc
        raise _reject(502, "Records service unavailable") from exc
    logger.info(
        "upload accepted: dataset %s user %s %d rows",
        dataset_id,
        access.claims.user_id,
        len(parsed.rows),
    )
    return DatasetUploadResponse(dataset_id=dataset_id, row_count=len(parsed.rows))


@router.get(
    "/datasets/{dataset_id}/rows",
    response_model=DatasetRowsPage,
    operation_id="list_dataset_rows",
    responses={
        401: {"model": ErrorDetail},
        403: {"model": ErrorDetail},
        404: {"model": ErrorDetail},
        502: {"model": ErrorDetail},
    },
)
async def get_dataset_rows(
    access: Annotated[DatasetAccess, Depends(require_dataset_role(Role.VIEWER))],
    db: Annotated[AsyncDatabase[dict[str, Any]], Depends(get_mongo_db)],
    after: Annotated[int | None, Query(ge=0)] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> DatasetRowsPage:
    """Keyset-page a dataset's rows in row_index order."""
    if access.dataset.row_count is None:
        return DatasetRowsPage(items=[], next_after=None)
    rows = await list_dataset_rows(db, access.dataset.id, after=after, limit=limit + 1)
    has_more = len(rows) > limit
    items = rows[:limit]
    return DatasetRowsPage(
        items=items,
        next_after=items[-1].row_index if has_more else None,
    )
