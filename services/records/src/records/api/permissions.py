"""Organization role lookups and the write-role permission class.

Roles are checked against Membership rows, not token claims: the token's org
map can be up to five minutes stale after a role change.
"""

from typing import Any, Protocol, cast

from django.contrib.auth.models import AbstractBaseUser, AnonymousUser
from rest_framework.permissions import SAFE_METHODS, BasePermission
from rest_framework.request import Request
from rest_framework.views import APIView

from records.accounts.models import Membership


class ScopedView(Protocol):
    """Viewset attributes the scoping helpers rely on."""

    organization_lookup: str
    write_roles: frozenset[str]


def role_in(user: AbstractBaseUser | AnonymousUser, organization_id: int) -> str | None:
    """Return the user's Membership role in the organization, or None."""
    return (
        Membership.objects.filter(user_id=cast(int, user.pk), organization_id=organization_id)
        .values_list("role", flat=True)
        .first()
    )


def organization_id_of(instance: Any, organization_lookup: str) -> int:
    """Walk the ORM lookup path from a record to its Organization's id.

    An empty lookup means the instance is the Organization itself.
    """
    target = instance
    if organization_lookup:
        for part in organization_lookup.split("__"):
            target = getattr(target, part)
    return int(target.pk)


class OrganizationRolePermission(BasePermission):
    """Restrict object writes to members whose role is in ``view.write_roles``.

    Reads are already scoped by the viewset's membership-filtered queryset, so
    this only gates non-safe methods; it runs from ``get_object`` for detail
    routes, before payload validation.
    """

    def has_object_permission(self, request: Request, view: APIView, obj: Any) -> bool:
        if request.method in SAFE_METHODS:
            return True
        scoped = cast("ScopedView", view)
        organization_id = organization_id_of(obj, scoped.organization_lookup)
        return role_in(request.user, organization_id) in scoped.write_roles
