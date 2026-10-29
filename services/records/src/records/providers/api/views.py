"""Viewsets for provider, model, and scorer configs."""

from typing import ClassVar

from records.api.viewsets import OrganizationScopedModelViewSet
from records.providers.models import ModelConfig, ProviderConfig, ScorerConfig

from .serializers import (
    ModelConfigSerializer,
    ProviderConfigSerializer,
    ScorerConfigSerializer,
)


class ProviderConfigViewSet(OrganizationScopedModelViewSet):
    queryset = ProviderConfig.objects.all()
    serializer_class = ProviderConfigSerializer
    organization_lookup = "organization"
    filter_params: ClassVar[dict[str, str]] = {"organization": "organization_id"}


class ModelConfigViewSet(OrganizationScopedModelViewSet):
    queryset = ModelConfig.objects.all()
    serializer_class = ModelConfigSerializer
    organization_lookup = "provider__organization"
    filter_params: ClassVar[dict[str, str]] = {"provider": "provider_id"}


class ScorerConfigViewSet(OrganizationScopedModelViewSet):
    queryset = ScorerConfig.objects.all()
    serializer_class = ScorerConfigSerializer
    organization_lookup = "project__organization"
    filter_params: ClassVar[dict[str, str]] = {"project": "project_id"}
