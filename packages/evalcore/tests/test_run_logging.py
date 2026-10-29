"""Tests for the shared run-id logging helpers."""

import io
import logging
from collections.abc import Iterator

import pytest

from evalcore import RunIdFilter, RunIdFormatter, configure_logging, run_id_var


@pytest.fixture()
def captured() -> Iterator[tuple[io.StringIO, logging.Logger]]:
    """A logger wired to a StringIO with the shared filter and formatter."""
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.addFilter(RunIdFilter())
    handler.setFormatter(RunIdFormatter("%(message)s"))
    logger = logging.getLogger("tests.evalcore.run_logging")
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    logger.propagate = False
    try:
        yield stream, logger
    finally:
        logger.removeHandler(handler)


def test_run_id_from_contextvar(captured: tuple[io.StringIO, logging.Logger]) -> None:
    stream, logger = captured
    token = run_id_var.set("run-42")
    try:
        logger.info("hello")
    finally:
        run_id_var.reset(token)
    assert "hello run_id=run-42" in stream.getvalue()


def test_run_id_from_extra(captured: tuple[io.StringIO, logging.Logger]) -> None:
    stream, logger = captured
    logger.info("hello", extra={"run_id": "run-99"})
    assert "hello run_id=run-99" in stream.getvalue()


def test_extra_run_id_wins_over_contextvar(
    captured: tuple[io.StringIO, logging.Logger],
) -> None:
    stream, logger = captured
    token = run_id_var.set("run-ctx")
    try:
        logger.info("hello", extra={"run_id": "run-explicit"})
    finally:
        run_id_var.reset(token)
    assert "hello run_id=run-explicit" in stream.getvalue()
    assert "run-ctx" not in stream.getvalue()


def test_no_run_id_omits_marker(captured: tuple[io.StringIO, logging.Logger]) -> None:
    stream, logger = captured
    logger.info("hello")
    assert "run_id=" not in stream.getvalue()


def _is_ours(handler: logging.Handler) -> bool:
    return any(isinstance(f, RunIdFilter) for f in handler.filters)


def test_configure_logging_idempotent() -> None:
    configure_logging()
    configure_logging()
    marked = [h for h in logging.getLogger().handlers if _is_ours(h)]
    assert len(marked) == 1
