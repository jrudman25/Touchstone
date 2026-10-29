"""Viewsets for projects, prompt templates/versions, and datasets."""

from typing import ClassVar

from rest_framework import mixins

from records.api.viewsets import (
    OrganizationScopedModelViewSet,
    OrganizationScopedViewSet,
)
from records.projects.models import Dataset, Project, PromptTemplate, PromptVersion

from .serializers import (
    DatasetSerializer,
    ProjectSerializer,
    PromptTemplateSerializer,
    PromptVersionSerializer,
)


class ProjectViewSet(OrganizationScopedModelViewSet):
    queryset = Project.objects.all()
    serializer_class = ProjectSerializer
    organization_lookup = "organization"
    filter_params: ClassVar[dict[str, str]] = {"organization": "organization_id"}


class PromptTemplateViewSet(OrganizationScopedModelViewSet):
    queryset = PromptTemplate.objects.all()
    serializer_class = PromptTemplateSerializer
    organization_lookup = "project__organization"
    filter_params: ClassVar[dict[str, str]] = {"project": "project_id"}


class PromptVersionViewSet(
    OrganizationScopedViewSet,
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.CreateModelMixin,
):
    """Immutable versions: create and read only, no update or delete."""

    queryset = PromptVersion.objects.all()
    serializer_class = PromptVersionSerializer
    organization_lookup = "template__project__organization"
    filter_params: ClassVar[dict[str, str]] = {"template": "template_id"}


class DatasetViewSet(OrganizationScopedModelViewSet):
    queryset = Dataset.objects.all()
    serializer_class = DatasetSerializer
    organization_lookup = "project__organization"
    filter_params: ClassVar[dict[str, str]] = {"project": "project_id"}
