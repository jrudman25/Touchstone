"""Organization endpoint: owner-only updates, no create or delete."""

import pytest
from rest_framework.test import APIClient

from records.accounts.models import Organization

pytestmark = pytest.mark.django_db

BASE = "/api/records/organizations/"


def test_owner_updates_organization(owner_client: APIClient, organization: Organization) -> None:
    response = owner_client.patch(
        f"{BASE}{organization.pk}/", {"name": "Acme Renamed"}, format="json"
    )
    assert response.status_code == 200
    organization.refresh_from_db()
    assert organization.name == "Acme Renamed"


def test_editor_update_is_403(editor_client: APIClient, organization: Organization) -> None:
    response = editor_client.patch(f"{BASE}{organization.pk}/", {"name": "hacked"}, format="json")
    assert response.status_code == 403
    organization.refresh_from_db()
    assert organization.name == "Acme"


def test_viewer_update_is_403(viewer_client: APIClient, organization: Organization) -> None:
    response = viewer_client.patch(f"{BASE}{organization.pk}/", {"name": "hacked"}, format="json")
    assert response.status_code == 403
    organization.refresh_from_db()
    assert organization.name == "Acme"


def test_create_is_405(owner_client: APIClient) -> None:
    response = owner_client.post(BASE, {"name": "New", "slug": "new"}, format="json")
    assert response.status_code == 405
    assert not Organization.objects.filter(slug="new").exists()


def test_delete_is_405(owner_client: APIClient, organization: Organization) -> None:
    response = owner_client.delete(f"{BASE}{organization.pk}/")
    assert response.status_code == 405
    assert Organization.objects.filter(pk=organization.pk).exists()
