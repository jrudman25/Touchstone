"""Organization-scoped viewset base classes.

Every record endpoint scopes its queryset to organizations the caller belongs
to (via Membership), applies declared query-param filters, gates creates on
``write_roles``, and turns protected deletes into 409s.
"""

from typing import Any, ClassVar

from django.db.models import ProtectedError, QuerySet, RestrictedError
from rest_framework import mixins, viewsets
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.serializers import BaseSerializer

from .exceptions import Conflict
from .permissions import OrganizationRolePermission, role_in


def organization_id_for_create(validated_data: dict[str, Any], organization_lookup: str) -> int:
    """Resolve the target Organization id from validated FK instances.

    Follows the first lookup part into ``validated_data`` (a model instance),
    then walks the rest of the path, e.g. ``project__organization``.
    """
    parts = organization_lookup.split("__")
    target = validated_data[parts[0]]
    for part in parts[1:]:
        target = getattr(target, part)
    return int(target.pk)


class OrganizationScopedViewSet(viewsets.GenericViewSet[Any]):
    """Shared scoping/filtering/write rules for record endpoints."""

    organization_lookup: ClassVar[str] = ""
    write_roles: ClassVar[frozenset[str]] = frozenset({"editor", "owner"})
    # Query-param name -> ORM lookup, e.g. {"project": "project_id"}.
    filter_params: ClassVar[dict[str, str]] = {}
    permission_classes = (IsAuthenticated, OrganizationRolePermission)

    def get_queryset(self) -> QuerySet[Any]:
        queryset = super().get_queryset()
        prefix = (
            f"{self.organization_lookup}__memberships__user"
            if self.organization_lookup
            else "memberships__user"
        )
        queryset = queryset.filter(**{prefix: self.request.user})
        if self.organization_lookup:
            queryset = queryset.select_related(self.organization_lookup)
        for param, lookup in self.filter_params.items():
            raw = self.request.query_params.get(param)
            if raw is None:
                continue
            try:
                value = int(raw)
            except ValueError:
                raise ValidationError({param: "Must be an integer."}) from None
            queryset = queryset.filter(**{lookup: value})
        return queryset.order_by("id")

    def perform_create(self, serializer: BaseSerializer[Any]) -> None:
        # Field validation already ran (foreign pks are 400s); the role check
        # comes before serializer.save(), which runs model full_clean.
        organization_id = organization_id_for_create(
            serializer.validated_data, self.organization_lookup
        )
        if role_in(self.request.user, organization_id) not in self.write_roles:
            raise PermissionDenied("Your role in this organization does not allow writes.")
        serializer.save()

    def perform_destroy(self, instance: Any) -> None:
        try:
            instance.delete()
        except (ProtectedError, RestrictedError) as exc:
            raise Conflict("Cannot delete: protected related records exist.") from exc


class OrganizationScopedModelViewSet(
    OrganizationScopedViewSet,
    mixins.CreateModelMixin,
    mixins.RetrieveModelMixin,
    mixins.UpdateModelMixin,
    mixins.DestroyModelMixin,
    mixins.ListModelMixin,
):
    """Full CRUD on organization-scoped records."""
