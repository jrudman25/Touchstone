"""Serializers for projects, prompt templates/versions, and datasets."""

from typing import Any

from rest_framework import serializers

from records.accounts.models import Organization
from records.api.fields import MemberScopedPrimaryKeyRelatedField
from records.api.validation import ModelCleanMixin
from records.projects.models import Dataset, Project, PromptTemplate, PromptVersion
from records.projects.services import create_prompt_version


class ProjectSerializer(ModelCleanMixin, serializers.ModelSerializer[Project]):
    organization = MemberScopedPrimaryKeyRelatedField(
        organization_lookup="", queryset=Organization.objects.all()
    )

    class Meta:
        model = Project
        fields = ["id", "organization", "name", "description", "baseline_run_id"]  # noqa: RUF012


class PromptTemplateSerializer(ModelCleanMixin, serializers.ModelSerializer[PromptTemplate]):
    project = MemberScopedPrimaryKeyRelatedField(
        organization_lookup="organization", queryset=Project.objects.all()
    )

    class Meta:
        model = PromptTemplate
        fields = ["id", "project", "name"]  # noqa: RUF012


class PromptVersionSerializer(serializers.ModelSerializer[PromptVersion]):
    """Versions are create/read only; number and variables are server-assigned."""

    template = MemberScopedPrimaryKeyRelatedField(
        organization_lookup="project__organization",
        queryset=PromptTemplate.objects.all(),
    )
    system_message = serializers.CharField(required=False, allow_blank=True, default="")

    class Meta:
        model = PromptVersion
        fields = [  # noqa: RUF012
            "id",
            "template",
            "system_message",
            "body",
            "number",
            "variables",
            "created_at",
        ]
        read_only_fields = ["number", "variables", "created_at"]  # noqa: RUF012

    def create(self, validated_data: dict[str, Any]) -> PromptVersion:
        return create_prompt_version(
            validated_data["template"],
            system_message=validated_data.get("system_message", ""),
            body=validated_data["body"],
        )


class DatasetSerializer(ModelCleanMixin, serializers.ModelSerializer[Dataset]):
    """row_count is set only by the upload path, never through this API."""

    project = MemberScopedPrimaryKeyRelatedField(
        organization_lookup="organization", queryset=Project.objects.all()
    )

    class Meta:
        model = Dataset
        fields = ["id", "project", "name", "row_count"]  # noqa: RUF012
        read_only_fields = ["row_count"]  # noqa: RUF012
