"""OpenAPI schema endpoint."""

import pytest
from rest_framework.test import APIClient

pytestmark = pytest.mark.django_db


def test_schema_unauthenticated_returns_openapi(api_client: APIClient) -> None:
    response = api_client.get("/api/records/schema/")
    assert response.status_code == 200
    body = response.json()
    assert "openapi" in body
    assert f"{response['Content-Type']}".startswith("application/")


def test_schema_documents_list_filter_params(api_client: APIClient) -> None:
    schema = api_client.get("/api/records/schema/").json()
    expected = {
        "/api/records/datasets/": "project",
        "/api/records/prompt-templates/": "project",
        "/api/records/prompt-versions/": "template",
        "/api/records/scorers/": "project",
        "/api/records/providers/": "organization",
        "/api/records/models/": "provider",
    }
    for path, param in expected.items():
        params = schema["paths"][path]["get"].get("parameters", [])
        names = [p["name"] for p in params]
        assert param in names, f"{path} missing {param} query param"
