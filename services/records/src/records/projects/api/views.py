"""Viewsets for projects, prompt templates/versions, and datasets."""

from typing import ClassVar

from django.db import transaction
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import extend_schema
from rest_framework import mixins
from rest_framework.decorators import action
from rest_framework.request import Request
from rest_framework.response import Response

from records.accounts.auth.serializers import DetailSerializer
from records.api.exceptions import Conflict
from records.api.viewsets import (
    OrganizationScopedModelViewSet,
    OrganizationScopedViewSet,
)
from records.projects.models import Dataset, Project, PromptTemplate, PromptVersion

from .serializers import (
    DatasetRowCountSerializer,
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

    @extend_schema(
        request=DatasetRowCountSerializer,
        responses={
            200: DatasetSerializer,
            400: OpenApiTypes.OBJECT,
            403: DetailSerializer,
            404: DetailSerializer,
            409: DetailSerializer,
        },
    )
    @action(detail=True, methods=["post"], url_path="set-row-count")
    def set_row_count(self, request: Request, pk: str | None = None) -> Response:
        """Set row_count once, while it is null; 409 afterwards."""
        instance = self.get_object()
        serializer = DatasetRowCountSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        with transaction.atomic():
            locked = (
                Dataset.objects.select_for_update()
                .select_related("project__organization")
                .get(pk=instance.pk)
            )
            if locked.row_count is not None:
                raise Conflict("row_count is already set.")
            locked.row_count = serializer.validated_data["row_count"]
            locked.save(update_fields=["row_count"])
        return Response(DatasetSerializer(locked).data)
