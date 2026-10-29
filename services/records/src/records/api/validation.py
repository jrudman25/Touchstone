"""Serializer mixin that routes writes through model ``full_clean``.

Per AGENTS.md, tenant and per-kind rules live in each model's ``clean()`` so
admin and API apply them identically. DRF serializers therefore must not
reimplement those rules: this mixin builds the candidate instance, runs
``full_clean``, and only then saves.
"""

import copy
from typing import Any

from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import models
from rest_framework.exceptions import ValidationError
from rest_framework.serializers import as_serializer_error


class ModelCleanMixin:
    """ModelSerializer create/update that applies the model's full_clean."""

    Meta: Any  # provided by ModelSerializer

    @staticmethod
    def _full_clean(instance: models.Model) -> None:
        try:
            instance.full_clean()
        except DjangoValidationError as exc:
            raise ValidationError(detail=as_serializer_error(exc)) from exc

    def create(self, validated_data: dict[str, Any]) -> Any:
        instance = self.Meta.model(**validated_data)
        self._full_clean(instance)
        instance.save()
        return instance

    def update(self, instance: Any, validated_data: dict[str, Any]) -> Any:
        # Validate a copy so a failed clean() leaves the real instance (and its
        # related-object cache) untouched.
        candidate = copy.copy(instance)
        for field, value in validated_data.items():
            setattr(candidate, field, value)
        self._full_clean(candidate)
        candidate.save()
        return candidate
