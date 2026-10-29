"""Viewsets for organizations and memberships."""

from typing import Any, ClassVar, cast

from django.db import transaction
from rest_framework import mixins
from rest_framework.exceptions import ValidationError
from rest_framework.serializers import BaseSerializer

from records.accounts.models import Membership, Organization
from records.accounts.ownership import LAST_OWNER_MESSAGE, is_last_owner
from records.api.viewsets import (
    OrganizationScopedModelViewSet,
    OrganizationScopedViewSet,
)

from .serializers import (
    MembershipSerializer,
    MembershipUpdateSerializer,
    OrganizationSerializer,
)


class OrganizationViewSet(
    OrganizationScopedViewSet,
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.UpdateModelMixin,
):
    """Read for members, update for owners; orgs are created via admin/seed."""

    queryset = Organization.objects.all()
    serializer_class = OrganizationSerializer
    organization_lookup = ""
    write_roles = frozenset({"owner"})


class MembershipViewSet(OrganizationScopedModelViewSet):
    """Members read; owners add, change roles, and remove memberships."""

    queryset = Membership.objects.select_related("organization", "user")
    organization_lookup = "organization"
    write_roles = frozenset({"owner"})
    filter_params: ClassVar[dict[str, str]] = {"organization": "organization_id"}

    def get_serializer_class(self) -> type[BaseSerializer[Any]]:
        if getattr(self, "action", None) in ("update", "partial_update"):
            return MembershipUpdateSerializer
        return MembershipSerializer

    def perform_update(self, serializer: BaseSerializer[Any]) -> None:
        instance = cast(Membership, serializer.instance)
        new_role = serializer.validated_data.get("role", instance.role)
        with transaction.atomic():
            if is_last_owner(instance) and new_role != Membership.Role.OWNER:
                raise ValidationError({"role": LAST_OWNER_MESSAGE})
            serializer.save()

    def perform_destroy(self, instance: Membership) -> None:
        with transaction.atomic():
            if is_last_owner(instance):
                raise ValidationError(LAST_OWNER_MESSAGE)
            super().perform_destroy(instance)
