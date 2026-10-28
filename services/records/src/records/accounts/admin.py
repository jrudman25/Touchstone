"""Admin registrations for the accounts app."""

from django.contrib import admin
from django.contrib.auth.admin import UserAdmin

from .models import Membership, Organization, User


@admin.register(User)
class RecordsUserAdmin(UserAdmin):
    """Standard user admin."""


@admin.register(Organization)
class OrganizationAdmin(admin.ModelAdmin):
    list_display = ("name", "slug")
    search_fields = ("name", "slug")


@admin.register(Membership)
class MembershipAdmin(admin.ModelAdmin):
    list_display = ("user", "organization", "role")
    list_filter = ("role",)
