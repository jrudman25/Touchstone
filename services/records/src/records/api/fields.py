"""Related fields scoped to the caller's organizations."""

from typing import Any

from django.db.models import QuerySet
from rest_framework import serializers


class MemberScopedPrimaryKeyRelatedField(serializers.PrimaryKeyRelatedField[Any]):
    """PrimaryKeyRelatedField limited to objects in the requester's orgs.

    ``organization_lookup`` is the ORM path from the related model to
    Organization ("" for Organization itself). Any pk outside the caller's
    organizations fails with the standard "does not exist" 400.
    """

    def __init__(self, *, organization_lookup: str, **kwargs: Any) -> None:
        self.organization_lookup = organization_lookup
        super().__init__(**kwargs)

    def get_queryset(self) -> QuerySet[Any]:
        queryset = super().get_queryset()
        if queryset is None:  # the field was declared without a queryset
            raise TypeError("MemberScopedPrimaryKeyRelatedField requires a queryset.")
        prefix = (
            f"{self.organization_lookup}__memberships__user"
            if self.organization_lookup
            else "memberships__user"
        )
        return queryset.filter(**{prefix: self.context["request"].user})
