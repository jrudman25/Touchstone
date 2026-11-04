"""Streaming parser for dataset JSONL uploads.

Pure function over an ``AsyncIterator[bytes]`` so it is testable without an
HTTP request. Raw bytes are counted against the byte limit as chunks
arrive; lines are split on ``\\n``, one trailing ``\\r`` is stripped per
line, and a UTF-8 BOM is stripped only at the very start of line 1. A
trailing newline does not create an extra line; every other line, blank
ones included, counts toward the 1-based line numbering and the row limit.
Error collection stops after ``MAX_ERRORS`` errors.
"""

from collections.abc import AsyncIterator
from dataclasses import dataclass, field

from pydantic import ValidationError

from evalcore import DatasetRowInput

MAX_ERRORS = 50


class UploadLimitError(Exception):
    """The upload exceeded a configured byte or row limit (HTTP 413)."""


@dataclass
class LineError:
    line: int
    message: str


@dataclass
class ParsedUpload:
    rows: list[DatasetRowInput] = field(default_factory=list)
    errors: list[LineError] = field(default_factory=list)
    line_count: int = 0


async def parse_jsonl_lines(
    stream: AsyncIterator[bytes],
    *,
    max_bytes: int,
    max_rows: int,
    max_errors: int = MAX_ERRORS,
) -> ParsedUpload:
    """Read ``stream`` to completion and validate every line.

    Raises ``UploadLimitError`` as soon as the byte or row limit is passed.
    Returns early once ``max_errors`` errors are collected, without reading
    the rest of the stream.
    """
    result = ParsedUpload()
    pending = b""
    total_bytes = 0

    def consume(raw: bytes) -> None:
        result.line_count += 1
        if result.line_count > max_rows:
            raise UploadLimitError(f"Upload exceeds {max_rows} rows")
        if result.line_count == 1 and raw.startswith(b"\xef\xbb\xbf"):
            raw = raw[3:]
        if raw.endswith(b"\r"):
            raw = raw[:-1]
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError:
            result.errors.append(LineError(result.line_count, "Line is not valid UTF-8"))
            return
        if not text.strip():
            result.errors.append(LineError(result.line_count, "Blank line"))
            return
        try:
            result.rows.append(DatasetRowInput.model_validate_json(text))
        except ValidationError as exc:
            error = exc.errors()[0]
            loc = ".".join(str(part) for part in error["loc"])
            message = f"{loc}: {error['msg']}" if loc else error["msg"]
            result.errors.append(LineError(result.line_count, message))

    async for chunk in stream:
        total_bytes += len(chunk)
        if total_bytes > max_bytes:
            raise UploadLimitError(f"Upload exceeds {max_bytes} bytes")
        pending += chunk
        *lines, pending = pending.split(b"\n")
        for raw in lines:
            consume(raw)
            if len(result.errors) >= max_errors:
                return result
    if pending:
        consume(pending)
    return result
