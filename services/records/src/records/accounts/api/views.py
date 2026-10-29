"""Viewsets for organizations and memberships."""

from typing import Any, ClassVar, cast

from django.db import transaction
from rest_framework import mixins
from rest_framework.exceptions import ValidationError
from rest_framework.serializers import BaseSerializer

from records.accounts.models import Membership, Organization
from records.api.viewsets import (
    OrganizationScopedModelViewSet,
    OrganizationScopedViewSet,
)

from .serializers import (
    MembershipSerializer,
    MembershipUpdateSerializer,
    OrganizationSerializer,
)

LAST_OWNER_MESSAGE = "An organization must keep at least one owner."


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

    @staticmethod
    def _is_last_owner(instance: Membership) -> bool:
        """True if removing/demoting this row leaves the org without an owner.

        Call inside transaction.atomic(): the owner rows are locked before the
        count is read.
        """
        owner_ids = list(
            Membership.objects.select_for_update()
            .filter(organization_id=instance.organization_id, role="owner")
            .values_list("id", flat=True)
        )
        return instance.pk in owner_ids and len(owner_ids) == 1

    def perform_update(self, serializer: BaseSerializer[Any]) -> None:
        instance = cast(Membership, serializer.instance)
        new_role = serializer.validated_data.get("role", instance.role)
        with transaction.atomic():
            if self._is_last_owner(instance) and new_role != Membership.Role.OWNER:
                raise ValidationError({"role": LAST_OWNER_MESSAGE})
            serializer.save()

    def perform_destroy(self, instance: Membership) -> None:
        with transaction.atomic():
            if self._is_last_owner(instance):
                raise ValidationError(LAST_OWNER_MESSAGE)
            super().perform_destroy(instance)
