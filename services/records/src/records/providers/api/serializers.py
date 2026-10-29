"""Serializers for provider, model, and scorer configs."""

from rest_framework import serializers

from records.accounts.models import Organization
from records.api.fields import MemberScopedPrimaryKeyRelatedField
from records.api.validation import ModelCleanMixin
from records.projects.models import Project
from records.providers.models import ModelConfig, ProviderConfig, ScorerConfig


class ProviderConfigSerializer(ModelCleanMixin, serializers.ModelSerializer[ProviderConfig]):
    organization = MemberScopedPrimaryKeyRelatedField(
        organization_lookup="", queryset=Organization.objects.all()
    )

    class Meta:
        model = ProviderConfig
        fields = [  # noqa: RUF012
            "id",
            "organization",
            "name",
            "kind",
            "base_url",
            "api_key_env",
            "max_concurrency",
            "requests_per_minute",
        ]


class ModelConfigSerializer(ModelCleanMixin, serializers.ModelSerializer[ModelConfig]):
    provider = MemberScopedPrimaryKeyRelatedField(
        organization_lookup="organization", queryset=ProviderConfig.objects.all()
    )

    class Meta:
        model = ModelConfig
        fields = [  # noqa: RUF012
            "id",
            "provider",
            "model_name",
            "temperature",
            "max_tokens",
            "context_length",
            "input_price_per_1k",
            "output_price_per_1k",
        ]


class ScorerConfigSerializer(ModelCleanMixin, serializers.ModelSerializer[ScorerConfig]):
    project = MemberScopedPrimaryKeyRelatedField(
        organization_lookup="organization", queryset=Project.objects.all()
    )

    class Meta:
        model = ScorerConfig
        fields = ["id", "project", "name", "kind", "params"]  # noqa: RUF012
