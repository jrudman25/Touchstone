"""Logging setup shared by FastAPI and the worker.

Every log record carries ``record.run_id``: taken from ``extra={"run_id": ...}``
when the call site passes one, otherwise from ``run_id_var`` (a context var the
service sets while it works on a run). The formatter appends ``run_id=<id>``
only when a record actually has one.
"""

import logging
import sys
from contextvars import ContextVar

run_id_var: ContextVar[str | None] = ContextVar("run_id", default=None)

_BASE_FORMAT = "%(asctime)s %(levelname)s %(name)s %(message)s"
_HANDLER_ATTR = "_evalcore_run_logging"


class RunIdFilter(logging.Filter):
    """Set ``record.run_id`` from ``extra`` when given, else the context var."""

    def filter(self, record: logging.LogRecord) -> bool:
        if not getattr(record, "run_id", None):
            record.run_id = run_id_var.get()
        return True


class RunIdFormatter(logging.Formatter):
    """Render the base format, appending ``run_id=<id>`` when present."""

    def format(self, record: logging.LogRecord) -> str:
        message = super().format(record)
        run_id = getattr(record, "run_id", None)
        if run_id:
            message = f"{message} run_id={run_id}"
        return message


def configure_logging(level: int | str = "INFO") -> None:
    """Install one stdout handler with the run-id filter and formatter.

    Idempotent: a second call only updates the root logger's level; it never
    adds another handler.
    """
    root = logging.getLogger()
    for handler in root.handlers:
        if getattr(handler, _HANDLER_ATTR, False):
            break
    else:
        handler = logging.StreamHandler(sys.stdout)
        setattr(handler, _HANDLER_ATTR, True)
        handler.addFilter(RunIdFilter())
        handler.setFormatter(RunIdFormatter(_BASE_FORMAT))
        root.addHandler(handler)
    root.setLevel(level)
