"""User, Organization, and Membership models."""

from django.contrib.auth.models import AbstractUser
from django.db import models

from records.tenancy import enforce_immutable_fk


class User(AbstractUser):
    """Custom user model so it can be extended later without a migration reset."""


class Organization(models.Model):
    """Tenant boundary for every other record."""

    name = models.CharField(max_length=255)
    slug = models.SlugField(unique=True)

    def __str__(self) -> str:
        return self.name


class Membership(models.Model):
    """A user's role within an organization."""

    class Role(models.TextChoices):
        OWNER = "owner", "Owner"
        EDITOR = "editor", "Editor"
        VIEWER = "viewer", "Viewer"

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="memberships")
    organization = models.ForeignKey(
        Organization, on_delete=models.CASCADE, related_name="memberships"
    )
    role = models.CharField(max_length=10, choices=Role.choices)

    class Meta:
        constraints = [  # noqa: RUF012
            models.UniqueConstraint(
                fields=["user", "organization"], name="membership_user_org_unique"
            ),
        ]

    def clean(self) -> None:
        super().clean()
        # Tenant moves are forbidden: neither side of a membership may change.
        enforce_immutable_fk(self, "user")
        enforce_immutable_fk(self, "organization")

    def __str__(self) -> str:
        return f"{self.user} @ {self.organization} ({self.role})"
