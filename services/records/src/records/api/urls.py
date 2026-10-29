"""Records API URLConf: auth endpoints, the DRF router, and the OpenAPI schema."""

from django.urls import include, path
from drf_spectacular.utils import extend_schema, extend_schema_view
from drf_spectacular.views import SpectacularJSONAPIView
from rest_framework.permissions import AllowAny
from rest_framework.routers import DefaultRouter

from records.accounts.api.views import MembershipViewSet, OrganizationViewSet
from records.projects.api.views import (
    DatasetViewSet,
    ProjectViewSet,
    PromptTemplateViewSet,
    PromptVersionViewSet,
)
from records.providers.api.views import (
    ModelConfigViewSet,
    ProviderConfigViewSet,
    ScorerConfigViewSet,
)


@extend_schema_view(get=extend_schema(exclude=True))
class RecordsSchemaView(SpectacularJSONAPIView):
    """JSON OpenAPI schema, public and excluded from the schema itself."""

    authentication_classes = ()
    permission_classes = (AllowAny,)


router = DefaultRouter()
router.register("organizations", OrganizationViewSet, basename="organizations")
router.register("memberships", MembershipViewSet, basename="memberships")
router.register("projects", ProjectViewSet, basename="projects")
router.register("prompt-templates", PromptTemplateViewSet, basename="prompt-templates")
router.register("prompt-versions", PromptVersionViewSet, basename="prompt-versions")
router.register("datasets", DatasetViewSet, basename="datasets")
router.register("providers", ProviderConfigViewSet, basename="providers")
router.register("models", ModelConfigViewSet, basename="models")
router.register("scorers", ScorerConfigViewSet, basename="scorers")

urlpatterns = [
    path("auth/", include("records.accounts.auth.urls")),
    path("schema/", RecordsSchemaView.as_view(), name="schema"),
    path("", include(router.urls)),
]
