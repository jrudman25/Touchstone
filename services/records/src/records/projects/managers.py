"""Immutability enforcement for PromptVersion queryset writes."""

from __future__ import annotations

from collections.abc import Iterable
from typing import TYPE_CHECKING, Any

from django.db import models

if TYPE_CHECKING:
    from .models import PromptVersion


class ImmutableRecordError(Exception):
    """Raised when code tries to modify or delete an immutable PromptVersion."""


class PromptVersionQuerySet(models.QuerySet["PromptVersion"]):
    """Blocks every queryset-level write path that mutates existing rows."""

    def update(self, **kwargs: Any) -> int:
        raise ImmutableRecordError("PromptVersion rows are immutable and cannot be updated.")

    def bulk_update(
        self,
        objs: Iterable[PromptVersion],
        fields: Iterable[str],
        batch_size: int | None = None,
    ) -> int:
        raise ImmutableRecordError("PromptVersion rows are immutable and cannot be updated.")

    def delete(self) -> tuple[int, dict[str, int]]:
        raise ImmutableRecordError("PromptVersion rows are immutable and cannot be deleted.")


PromptVersionManager = models.Manager.from_queryset(PromptVersionQuerySet)
