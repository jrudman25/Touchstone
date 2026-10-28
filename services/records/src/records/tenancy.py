"""Tenant-boundary validation shared by model clean() methods.

SPEC.md forbids tenant moves (decision 41): an existing record can never
change organizations, directly or through reparenting, on any supported write
path. These helpers are called from each model's clean() so Django admin and
the DRF serializers apply the same rules.
"""

from typing import Protocol, cast

from django.core.exceptions import ValidationError
from django.db import models


class _HasOrganization(Protocol):
    organization_id: int


def _saved_instance[M: models.Model](instance: M) -> M | None:
    """Return the persisted version of an instance, or None if it is new."""
    if instance.pk is None:
        return None
    return type(instance)._default_manager.filter(pk=instance.pk).first()


def enforce_immutable_fk(instance: models.Model, field_name: str) -> None:
    """Reject any change to a foreign key on an existing row."""
    original = _saved_instance(instance)
    new_id = getattr(instance, f"{field_name}_id")
    if original is None or new_id is None:
        # New row, or a missing FK already reported by field validation.
        return
    if getattr(original, f"{field_name}_id") != new_id:
        raise ValidationError({field_name: f"{field_name} cannot be changed once created."})


def enforce_same_org_fk(instance: models.Model, field_name: str) -> None:
    """Allow reparenting only to a parent in the same organization.

    The referenced parent object must expose an ``organization_id`` attribute
    (directly or through its own parent, e.g. ``provider.organization_id``).
    """
    original = _saved_instance(instance)
    if original is None:
        return
    old_parent_id = getattr(original, f"{field_name}_id")
    new_parent_id = getattr(instance, f"{field_name}_id")
    if old_parent_id == new_parent_id or new_parent_id is None:
        return
    parent_model = type(instance)._meta.get_field(field_name).related_model
    if parent_model is None:  # pragma: no cover - FK fields always have one
        raise TypeError(f"{field_name} is not a relation")
    new_parent = cast("_HasOrganization", parent_model._default_manager.get(pk=new_parent_id))
    old_parent = cast("_HasOrganization", parent_model._default_manager.get(pk=old_parent_id))
    if new_parent.organization_id != old_parent.organization_id:
        raise ValidationError(
            {field_name: f"{field_name} cannot be moved to a different organization."}
        )
