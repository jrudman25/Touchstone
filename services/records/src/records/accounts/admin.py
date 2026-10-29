"""Admin registrations for the accounts app."""

from collections.abc import Sequence
from typing import Any

from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.db.models import QuerySet
from django.http import HttpRequest

from .models import Membership, Organization, User
from .ownership import (
    LAST_OWNER_MESSAGE,
    is_last_owner,
    memberships_leaving_orgs_ownerless,
)

_DeletedObjects = tuple[list[str], dict[str, int], set[str], list[str]]


def _protected_entries(memberships: Sequence[Membership] | QuerySet[Membership]) -> list[str]:
    return [
        f"{membership} ({LAST_OWNER_MESSAGE})"
        for membership in memberships_leaving_orgs_ownerless(memberships)
    ]


@admin.register(User)
class RecordsUserAdmin(UserAdmin):
    """User admin that refuses deletes which would orphan an organization."""

    def get_deleted_objects(
        self, objs: Sequence[User] | QuerySet[User], request: HttpRequest
    ) -> _DeletedObjects:
        deleted_objects, model_count, perms_needed, protected = super().get_deleted_objects(
            objs, request
        )
        protected = list(protected)
        protected.extend(_protected_entries(Membership.objects.filter(user__in=objs)))
        return deleted_objects, model_count, perms_needed, protected

    def delete_model(self, request: HttpRequest, obj: User) -> None:
        with transaction.atomic():
            if memberships_leaving_orgs_ownerless(obj.memberships.all()):
                raise PermissionDenied(LAST_OWNER_MESSAGE)
            super().delete_model(request, obj)

    def delete_queryset(self, request: HttpRequest, queryset: QuerySet[Any]) -> None:
        with transaction.atomic():
            if memberships_leaving_orgs_ownerless(Membership.objects.filter(user__in=queryset)):
                raise PermissionDenied(LAST_OWNER_MESSAGE)
            super().delete_queryset(request, queryset)


@admin.register(Organization)
class OrganizationAdmin(admin.ModelAdmin):
    list_display = ("name", "slug")
    search_fields = ("name", "slug")


@admin.register(Membership)
class MembershipAdmin(admin.ModelAdmin):
    list_display = ("user", "organization", "role")
    list_filter = ("role",)

    def get_deleted_objects(
        self, objs: Sequence[Membership] | QuerySet[Membership], request: HttpRequest
    ) -> _DeletedObjects:
        deleted_objects, model_count, perms_needed, protected = super().get_deleted_objects(
            objs, request
        )
        protected = list(protected)
        protected.extend(_protected_entries(objs))
        return deleted_objects, model_count, perms_needed, protected

    def delete_model(self, request: HttpRequest, obj: Membership) -> None:
        with transaction.atomic():
            if is_last_owner(obj):
                raise PermissionDenied(LAST_OWNER_MESSAGE)
            super().delete_model(request, obj)

    def delete_queryset(self, request: HttpRequest, queryset: QuerySet[Any]) -> None:
        with transaction.atomic():
            if memberships_leaving_orgs_ownerless(queryset):
                raise PermissionDenied(LAST_OWNER_MESSAGE)
            super().delete_queryset(request, queryset)
