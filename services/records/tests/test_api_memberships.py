"""Membership endpoint: create by username, role updates, last-owner rule."""

import pytest
from rest_framework.test import APIClient

from records.accounts.models import Membership, Organization, User

pytestmark = pytest.mark.django_db

BASE = "/api/records/memberships/"


def test_owner_creates_membership_by_username(
    owner_client: APIClient, organization: Organization, nonmember_user: User
) -> None:
    response = owner_client.post(
        BASE,
        {
            "username": nonmember_user.username,
            "organization": organization.pk,
            "role": "viewer",
        },
        format="json",
    )
    assert response.status_code == 201, response.json()
    body = response.json()
    assert body["username"] == nonmember_user.username
    assert body["user_id"] == nonmember_user.pk
    assert body["organization"] == organization.pk
    assert body["role"] == "viewer"
    assert Membership.objects.filter(user=nonmember_user, organization=organization).exists()


def test_create_unknown_username_is_400(
    owner_client: APIClient, organization: Organization
) -> None:
    response = owner_client.post(
        BASE,
        {"username": "ghost", "organization": organization.pk, "role": "viewer"},
        format="json",
    )
    assert response.status_code == 400


def test_duplicate_membership_is_400(
    owner_client: APIClient, membership: Membership, user: User, organization: Organization
) -> None:
    response = owner_client.post(
        BASE,
        {"username": user.username, "organization": organization.pk, "role": "viewer"},
        format="json",
    )
    assert response.status_code == 400


def test_last_owner_delete_is_400(owner_client: APIClient, membership: Membership) -> None:
    response = owner_client.delete(f"{BASE}{membership.pk}/")
    assert response.status_code == 400
    assert Membership.objects.filter(pk=membership.pk).exists()


def test_last_owner_demotion_is_400(owner_client: APIClient, membership: Membership) -> None:
    response = owner_client.patch(f"{BASE}{membership.pk}/", {"role": "editor"}, format="json")
    assert response.status_code == 400
    membership.refresh_from_db()
    assert membership.role == "owner"


def test_demote_owner_when_second_owner_exists(
    owner_client: APIClient,
    membership: Membership,
    organization: Organization,
    nonmember_user: User,
) -> None:
    Membership.objects.create(user=nonmember_user, organization=organization, role="owner")
    response = owner_client.patch(f"{BASE}{membership.pk}/", {"role": "editor"}, format="json")
    assert response.status_code == 200
    membership.refresh_from_db()
    assert membership.role == "editor"


def test_editor_cannot_write_memberships(
    editor_client: APIClient,
    membership: Membership,
    organization: Organization,
    nonmember_user: User,
) -> None:
    response = editor_client.post(
        BASE,
        {
            "username": nonmember_user.username,
            "organization": organization.pk,
            "role": "viewer",
        },
        format="json",
    )
    assert response.status_code == 403
    assert (
        editor_client.patch(
            f"{BASE}{membership.pk}/", {"role": "viewer"}, format="json"
        ).status_code
        == 403
    )
    assert editor_client.delete(f"{BASE}{membership.pk}/").status_code == 403
    membership.refresh_from_db()
    assert membership.role == "owner"


def test_patch_ignores_username_and_organization(
    owner_client: APIClient,
    membership: Membership,
    user: User,
    organization: Organization,
    other_organization: Organization,
    nonmember_user: User,
) -> None:
    Membership.objects.create(user=nonmember_user, organization=organization, role="owner")
    response = owner_client.patch(
        f"{BASE}{membership.pk}/",
        {
            "role": "editor",
            "username": nonmember_user.username,
            "organization": other_organization.pk,
        },
        format="json",
    )
    assert response.status_code == 200, response.json()
    membership.refresh_from_db()
    assert membership.role == "editor"
    assert membership.user_id == user.pk
    assert membership.organization_id == organization.pk


def test_organization_filter(
    owner_client: APIClient,
    membership: Membership,
    organization: Organization,
    nonmember_user: User,
) -> None:
    second = Membership.objects.create(
        user=nonmember_user, organization=organization, role="viewer"
    )
    response = owner_client.get(f"{BASE}?organization={organization.pk}")
    assert response.status_code == 200
    ids = {row["id"] for row in response.json()["results"]}
    assert ids == {membership.pk, second.pk}
