"""Cross-route tenancy coverage: auth, scoping, role gates, filters, paging."""

from typing import Any

import pytest
from rest_framework.test import APIClient

from records.accounts.models import Membership, Organization, User
from records.projects.models import (
    Dataset,
    Project,
    PromptTemplate,
    PromptVersion,
)
from records.providers.models import ModelConfig, ProviderConfig, ScorerConfig

pytestmark = pytest.mark.django_db

BASE = "/api/records"

ROUTES = [
    "organizations",
    "memberships",
    "projects",
    "prompt-templates",
    "prompt-versions",
    "datasets",
    "providers",
    "models",
    "scorers",
]

# A row in the caller's organization per route.
OWNED = {
    "organizations": "organization",
    "memberships": "membership",
    "projects": "project",
    "prompt-templates": "template",
    "prompt-versions": "prompt_version",
    "datasets": "dataset",
    "providers": "provider",
    "models": "model_config",
    "scorers": "scorer",
}

# A row in a foreign organization per route.
FOREIGN = {
    "organizations": "other_organization",
    "memberships": "other_org_membership",
    "projects": "other_project",
    "prompt-templates": "other_template",
    "prompt-versions": "other_version",
    "datasets": "other_dataset",
    "providers": "other_provider",
    "models": "other_org_model_config",
    "scorers": "other_scorer",
}

MODELS: dict[str, Any] = {
    "organizations": Organization,
    "memberships": Membership,
    "projects": Project,
    "prompt-templates": PromptTemplate,
    "prompt-versions": PromptVersion,
    "datasets": Dataset,
    "providers": ProviderConfig,
    "models": ModelConfig,
    "scorers": ScorerConfig,
}

# Routes accepting POST on the list (organizations has no create).
CREATABLE = [route for route in ROUTES if route != "organizations"]

# Detail routes accepting PATCH / DELETE.
PATCHABLE = [route for route in ROUTES if route != "prompt-versions"]
DELETABLE = [route for route in ROUTES if route not in ("organizations", "prompt-versions")]

# field -> attempted value for viewer PATCH attempts.
PATCH_ATTEMPT = {
    "organizations": ("name", "hacked"),
    "memberships": ("role", "viewer"),
    "projects": ("name", "hacked"),
    "prompt-templates": ("name", "hacked"),
    "datasets": ("name", "hacked"),
    "providers": ("name", "hacked"),
    "models": ("model_name", "hacked"),
    "scorers": ("name", "hacked"),
}

# route -> (query param, fixture for the scoped parent, fixture for the row)
FILTERS = {
    "memberships": ("organization", "organization", "membership"),
    "projects": ("organization", "organization", "project"),
    "prompt-templates": ("project", "project", "template"),
    "prompt-versions": ("template", "template", "prompt_version"),
    "datasets": ("project", "project", "dataset"),
    "providers": ("organization", "organization", "provider"),
    "models": ("provider", "provider", "model_config"),
    "scorers": ("project", "project", "scorer"),
}

FOREIGN_FILTERS = {
    "memberships": ("organization", "other_organization"),
    "projects": ("organization", "other_organization"),
    "prompt-templates": ("project", "other_project"),
    "prompt-versions": ("template", "other_template"),
    "datasets": ("project", "other_project"),
    "providers": ("organization", "other_organization"),
    "models": ("provider", "other_provider"),
    "scorers": ("project", "other_project"),
}


@pytest.fixture
def create_payloads(
    organization: Organization,
    project: Project,
    template: PromptTemplate,
    provider: ProviderConfig,
    nonmember_user: User,
) -> dict[str, dict[str, object]]:
    return {
        "memberships": {
            "username": nonmember_user.username,
            "organization": organization.pk,
            "role": "viewer",
        },
        "projects": {"organization": organization.pk, "name": "P2", "description": ""},
        "prompt-templates": {"project": project.pk, "name": "t2"},
        "prompt-versions": {"template": template.pk, "body": "hi {{x}}"},
        "datasets": {"project": project.pk, "name": "d2"},
        "providers": {"organization": organization.pk, "name": "p2", "kind": "mock"},
        "models": {
            "provider": provider.pk,
            "model_name": "m2",
            "max_tokens": 8,
            "context_length": 128,
        },
        "scorers": {"project": project.pk, "name": "s2", "kind": "exact", "params": {}},
    }


@pytest.fixture
def foreign_payloads(
    other_organization: Organization,
    other_project: Project,
    other_template: PromptTemplate,
    other_provider: ProviderConfig,
    nonmember_user: User,
) -> dict[str, dict[str, object]]:
    """Create bodies whose referenced parent lives in another organization."""
    return {
        "memberships": {
            "username": nonmember_user.username,
            "organization": other_organization.pk,
            "role": "viewer",
        },
        "projects": {"organization": other_organization.pk, "name": "x"},
        "prompt-templates": {"project": other_project.pk, "name": "x"},
        "prompt-versions": {"template": other_template.pk, "body": "x"},
        "datasets": {"project": other_project.pk, "name": "x"},
        "providers": {"organization": other_organization.pk, "name": "x", "kind": "mock"},
        "models": {
            "provider": other_provider.pk,
            "model_name": "x",
            "max_tokens": 8,
            "context_length": 128,
        },
        "scorers": {"project": other_project.pk, "name": "x", "kind": "exact", "params": {}},
    }


# --- authentication and tenant scoping -----------------------------------------


@pytest.mark.parametrize("route", ROUTES)
def test_unauthenticated_list_is_401(api_client: APIClient, route: str) -> None:
    assert api_client.get(f"{BASE}/{route}/").status_code == 401


@pytest.mark.parametrize("route", ROUTES)
def test_foreign_row_404_and_absent_from_list(
    owner_client: APIClient, route: str, request: pytest.FixtureRequest
) -> None:
    obj = request.getfixturevalue(FOREIGN[route])
    assert owner_client.get(f"{BASE}/{route}/{obj.pk}/").status_code == 404
    response = owner_client.get(f"{BASE}/{route}/")
    assert response.status_code == 200
    ids = {row["id"] for row in response.json()["results"]}
    assert obj.pk not in ids


@pytest.mark.parametrize("route", CREATABLE)
def test_create_referencing_foreign_parent_is_400(
    owner_client: APIClient,
    route: str,
    foreign_payloads: dict[str, dict[str, object]],
) -> None:
    before = MODELS[route].objects.count()
    response = owner_client.post(f"{BASE}/{route}/", foreign_payloads[route], format="json")
    assert response.status_code == 400
    assert MODELS[route].objects.count() == before


# --- role gates ------------------------------------------------------------------


@pytest.mark.parametrize("route", CREATABLE)
def test_viewer_create_is_403(
    viewer_client: APIClient,
    route: str,
    create_payloads: dict[str, dict[str, object]],
) -> None:
    before = MODELS[route].objects.count()
    response = viewer_client.post(f"{BASE}/{route}/", create_payloads[route], format="json")
    assert response.status_code == 403
    assert MODELS[route].objects.count() == before


@pytest.mark.parametrize("route", PATCHABLE)
def test_viewer_patch_is_403(
    viewer_client: APIClient, route: str, request: pytest.FixtureRequest
) -> None:
    obj = request.getfixturevalue(OWNED[route])
    field, attempted = PATCH_ATTEMPT[route]
    original = getattr(obj, field)
    response = viewer_client.patch(f"{BASE}/{route}/{obj.pk}/", {field: attempted}, format="json")
    assert response.status_code == 403
    obj.refresh_from_db()
    assert getattr(obj, field) == original


@pytest.mark.parametrize("route", DELETABLE)
def test_viewer_delete_is_403(
    viewer_client: APIClient, route: str, request: pytest.FixtureRequest
) -> None:
    obj = request.getfixturevalue(OWNED[route])
    response = viewer_client.delete(f"{BASE}/{route}/{obj.pk}/")
    assert response.status_code == 403
    assert MODELS[route].objects.filter(pk=obj.pk).exists()


@pytest.mark.parametrize("route", CREATABLE)
def test_owner_create_is_201(
    owner_client: APIClient,
    route: str,
    create_payloads: dict[str, dict[str, object]],
) -> None:
    response = owner_client.post(f"{BASE}/{route}/", create_payloads[route], format="json")
    assert response.status_code == 201, response.json()
    assert response.json()["id"]


# --- query-param filters ---------------------------------------------------------


@pytest.mark.parametrize("route", list(FILTERS))
def test_filter_param_selects_rows(
    owner_client: APIClient, route: str, request: pytest.FixtureRequest
) -> None:
    param, scope_fixture, row_fixture = FILTERS[route]
    scope = request.getfixturevalue(scope_fixture)
    row = request.getfixturevalue(row_fixture)
    response = owner_client.get(f"{BASE}/{route}/?{param}={scope.pk}")
    assert response.status_code == 200
    ids = {item["id"] for item in response.json()["results"]}
    assert row.pk in ids


@pytest.mark.parametrize("route", list(FOREIGN_FILTERS))
def test_filter_by_foreign_parent_returns_empty(
    owner_client: APIClient, route: str, request: pytest.FixtureRequest
) -> None:
    param, scope_fixture = FOREIGN_FILTERS[route]
    scope = request.getfixturevalue(scope_fixture)
    response = owner_client.get(f"{BASE}/{route}/?{param}={scope.pk}")
    assert response.status_code == 200
    assert response.json()["results"] == []


@pytest.mark.parametrize("route", list(FILTERS))
def test_filter_non_integer_is_400(owner_client: APIClient, route: str) -> None:
    param = FILTERS[route][0]
    response = owner_client.get(f"{BASE}/{route}/?{param}=abc")
    assert response.status_code == 400
    assert param in response.json()


# --- pagination -------------------------------------------------------------------


def test_pagination_envelope_and_page_size(owner_client: APIClient, project: Project) -> None:
    for index in range(3):
        Dataset.objects.create(project=project, name=f"d{index}")
    response = owner_client.get(f"{BASE}/datasets/?page_size=2")
    assert response.status_code == 200
    body = response.json()
    assert set(body) == {"count", "next", "previous", "results"}
    assert body["count"] == 3
    assert len(body["results"]) == 2
    assert body["next"] is not None
    assert body["previous"] is None
