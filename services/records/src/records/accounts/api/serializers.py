"""Serializers for organizations and memberships."""

from typing import Any, ClassVar

from rest_framework import serializers

from records.accounts.models import Membership, Organization, User
from records.api.fields import MemberScopedPrimaryKeyRelatedField
from records.api.validation import ModelCleanMixin


class OrganizationSerializer(ModelCleanMixin, serializers.ModelSerializer[Organization]):
    class Meta:
        model = Organization
        fields = ["id", "name", "slug"]  # noqa: RUF012


class MembershipSerializer(ModelCleanMixin, serializers.ModelSerializer[Membership]):
    """Create/read shape: members are added by username."""

    username = serializers.SlugRelatedField(
        slug_field="username",
        source="user",
        queryset=User.objects.filter(is_active=True),
    )
    user_id = serializers.IntegerField(read_only=True)
    organization = MemberScopedPrimaryKeyRelatedField(
        organization_lookup="", queryset=Organization.objects.all()
    )

    class Meta:
        model = Membership
        fields = ["id", "user_id", "username", "organization", "role"]  # noqa: RUF012


class MembershipUpdateSerializer(ModelCleanMixin, serializers.ModelSerializer[Membership]):
    """Update shape: only the role may change (user and org are immutable)."""

    username: serializers.SlugRelatedField[User] = serializers.SlugRelatedField(
        slug_field="username", source="user", read_only=True
    )
    user_id = serializers.IntegerField(read_only=True)
    organization: serializers.PrimaryKeyRelatedField[Organization] = (
        serializers.PrimaryKeyRelatedField(read_only=True)
    )

    class Meta:
        model = Membership
        fields = ["id", "user_id", "username", "organization", "role"]  # noqa: RUF012
        validators: ClassVar[list[Any]] = []
