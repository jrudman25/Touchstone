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
