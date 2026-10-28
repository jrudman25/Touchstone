"""Project, PromptTemplate, PromptVersion, and Dataset models."""

from typing import Any

from django.core.validators import RegexValidator
from django.db import models

from records.tenancy import enforce_immutable_fk, enforce_same_org_fk

from .managers import ImmutableRecordError, PromptVersionManager

BASELINE_RUN_ID_RE = r"^[0-9a-f]{24}$"
baseline_run_id_validator = RegexValidator(
    BASELINE_RUN_ID_RE,
    message="Must be null or a 24-character lowercase hex string (a MongoDB ObjectId).",
)


class Project(models.Model):
    """Groups prompts, datasets, and runs within an organization."""

    organization = models.ForeignKey(
        "accounts.Organization", on_delete=models.CASCADE, related_name="projects"
    )
    name = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    baseline_run_id = models.CharField(
        max_length=24,
        null=True,
        blank=True,
        validators=[baseline_run_id_validator],
        help_text="MongoDB ObjectId (hex) of the run marked as the comparison baseline.",
    )

    class Meta:
        constraints = [  # noqa: RUF012
            models.CheckConstraint(
                condition=models.Q(baseline_run_id__isnull=True)
                | models.Q(baseline_run_id__regex=BASELINE_RUN_ID_RE),
                name="project_baseline_run_id_hex_or_null",
            ),
        ]

    def clean(self) -> None:
        super().clean()
        # Tenant moves are forbidden: a project never changes organizations.
        enforce_immutable_fk(self, "organization")

    def __str__(self) -> str:
        return self.name


class PromptTemplate(models.Model):
    """A stable named prompt that immutable versions hang from."""

    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name="prompt_templates")
    name = models.CharField(max_length=255)

    def clean(self) -> None:
        super().clean()
        enforce_same_org_fk(self, "project")

    def __str__(self) -> str:
        return f"{self.project}: {self.name}"


class PromptVersion(models.Model):
    """One immutable revision of a prompt template.

    Every field is assigned at creation by
    :func:`records.projects.services.create_prompt_version`; all update and
    delete paths (instance and queryset) raise ImmutableRecordError.
    """

    template = models.ForeignKey(PromptTemplate, on_delete=models.PROTECT, related_name="versions")
    number = models.PositiveIntegerField()
    system_message = models.TextField(blank=True)
    body = models.TextField()
    variables = models.JSONField(default=list, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    objects = PromptVersionManager()

    class Meta:
        constraints = [  # noqa: RUF012
            models.UniqueConstraint(
                fields=["template", "number"], name="promptversion_template_number_unique"
            ),
        ]

    def save(self, *args: Any, **kwargs: Any) -> None:
        if not self._state.adding:
            raise ImmutableRecordError("PromptVersion rows are immutable and cannot be updated.")
        super().save(*args, **kwargs)

    def delete(self, *args: Any, **kwargs: Any) -> tuple[int, dict[str, int]]:
        raise ImmutableRecordError("PromptVersion rows are immutable and cannot be deleted.")

    def __str__(self) -> str:
        return f"{self.template} v{self.number}"


class Dataset(models.Model):
    """Dataset metadata; the rows themselves live in MongoDB dataset_rows."""

    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name="datasets")
    name = models.CharField(max_length=255)
    row_count = models.PositiveIntegerField(null=True, blank=True, default=None)

    def clean(self) -> None:
        super().clean()
        enforce_same_org_fk(self, "project")

    def __str__(self) -> str:
        return f"{self.project}: {self.name}"
