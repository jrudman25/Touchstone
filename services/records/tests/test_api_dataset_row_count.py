"""The set-row-count action and the dataset organization field."""

import pytest
from rest_framework.test import APIClient

from records.accounts.models import Organization
from records.projects.models import Dataset, Project

pytestmark = pytest.mark.django_db

BASE = "/api/records/datasets"


def url(dataset: Dataset) -> str:
    return f"{BASE}/{dataset.pk}/set-row-count/"


def test_editor_sets_row_count_once(
    editor_client: APIClient, dataset: Dataset, organization: Organization
) -> None:
    response = editor_client.post(url(dataset), {"row_count": 7}, format="json")
    assert response.status_code == 200, response.json()
    body = response.json()
    assert body["row_count"] == 7
    assert body["organization"] == organization.pk
    dataset.refresh_from_db()
    assert dataset.row_count == 7

    second = editor_client.post(url(dataset), {"row_count": 3}, format="json")
    assert second.status_code == 409
    dataset.refresh_from_db()
    assert dataset.row_count == 7


def test_owner_can_set_row_count(owner_client: APIClient, dataset: Dataset) -> None:
    response = owner_client.post(url(dataset), {"row_count": 0}, format="json")
    assert response.status_code == 200, response.json()
    dataset.refresh_from_db()
    assert dataset.row_count == 0


def test_viewer_set_row_count_is_403_and_unchanged(
    viewer_client: APIClient, dataset: Dataset
) -> None:
    response = viewer_client.post(url(dataset), {"row_count": 5}, format="json")
    assert response.status_code == 403
    dataset.refresh_from_db()
    assert dataset.row_count is None


def test_other_organizations_dataset_is_404(
    owner_client: APIClient, other_dataset: Dataset
) -> None:
    response = owner_client.post(url(other_dataset), {"row_count": 5}, format="json")
    assert response.status_code == 404
    other_dataset.refresh_from_db()
    assert other_dataset.row_count is None


def test_negative_row_count_is_400(editor_client: APIClient, dataset: Dataset) -> None:
    response = editor_client.post(url(dataset), {"row_count": -1}, format="json")
    assert response.status_code == 400
    dataset.refresh_from_db()
    assert dataset.row_count is None


@pytest.mark.parametrize(
    "payload",
    [
        {"row_count": "abc"},
        {"row_count": 2.5},
        {},
    ],
)
def test_invalid_body_is_400(
    editor_client: APIClient, dataset: Dataset, payload: dict[str, object]
) -> None:
    response = editor_client.post(url(dataset), payload, format="json")
    assert response.status_code == 400
    dataset.refresh_from_db()
    assert dataset.row_count is None


def test_missing_body_is_400(editor_client: APIClient, dataset: Dataset) -> None:
    response = editor_client.post(url(dataset))
    assert response.status_code == 400
    dataset.refresh_from_db()
    assert dataset.row_count is None


def test_patch_cannot_change_row_count(
    editor_client: APIClient, dataset: Dataset, project: Project
) -> None:
    response = editor_client.patch(
        f"{BASE}/{dataset.pk}/",
        {"project": project.pk, "name": "renamed", "row_count": 9},
        format="json",
    )
    assert response.status_code == 200, response.json()
    dataset.refresh_from_db()
    assert dataset.name == "renamed"
    assert dataset.row_count is None


def test_put_cannot_change_row_count(
    editor_client: APIClient, dataset: Dataset, project: Project
) -> None:
    response = editor_client.put(
        f"{BASE}/{dataset.pk}/",
        {"project": project.pk, "name": "renamed", "row_count": 9},
        format="json",
    )
    assert response.status_code == 200, response.json()
    dataset.refresh_from_db()
    assert dataset.row_count is None


def test_dataset_retrieve_and_list_include_organization(
    owner_client: APIClient, dataset: Dataset, project: Project, organization: Organization
) -> None:
    detail = owner_client.get(f"{BASE}/{dataset.pk}/")
    assert detail.status_code == 200
    assert detail.json()["organization"] == organization.pk

    listing = owner_client.get(f"{BASE}/")
    assert listing.status_code == 200
    match = [row for row in listing.json()["results"] if row["id"] == dataset.pk]
    assert match[0]["organization"] == organization.pk
