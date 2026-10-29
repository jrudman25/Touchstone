"""Last-owner enforcement in Membership.clean() and Django admin deletes."""

import pytest
from django.core.exceptions import ValidationError
from django.test import Client
from django.urls import reverse

from records.accounts.models import Membership, Organization, User
from records.accounts.ownership import LAST_OWNER_MESSAGE

pytestmark = pytest.mark.django_db


def _user(username: str) -> User:
    return User.objects.create_user(username=username, password="pw-12345")


def _owner(username: str, organization: Organization) -> Membership:
    return Membership.objects.create(user=_user(username), organization=organization, role="owner")


def _change_url(membership: Membership) -> str:
    return reverse("admin:accounts_membership_change", args=[membership.pk])


def _delete_url(model: str, pk: int) -> str:
    return reverse(f"admin:accounts_{model}_delete", args=[pk])


def _changelist_url(model: str) -> str:
    return reverse(f"admin:accounts_{model}_changelist")


def _membership_post_data(membership: Membership, role: str) -> dict[str, object]:
    return {
        "user": membership.user_id,
        "organization": membership.organization_id,
        "role": role,
    }


# --- Membership.clean() -------------------------------------------------------


def test_clean_demoting_last_owner_fails(membership: Membership) -> None:
    membership.role = "editor"
    with pytest.raises(ValidationError) as exc_info:
        membership.full_clean()
    assert "role" in exc_info.value.error_dict
    assert LAST_OWNER_MESSAGE in str(exc_info.value.error_dict["role"])
    membership.refresh_from_db()
    assert membership.role == "owner"


def test_clean_demote_with_second_owner_passes(
    membership: Membership, organization: Organization
) -> None:
    _owner("bob", organization)
    membership.role = "editor"
    membership.full_clean()
    membership.save()
    membership.refresh_from_db()
    assert membership.role == "editor"


def test_clean_new_membership_viewer_passes(organization: Organization) -> None:
    new = Membership(user=_user("carol"), organization=organization, role="viewer")
    new.full_clean()


def test_clean_non_owner_role_change_passes(organization: Organization) -> None:
    _owner("alice", organization)
    viewer = Membership.objects.create(user=_user("dave"), organization=organization, role="viewer")
    viewer.role = "editor"
    viewer.full_clean()
    viewer.save()
    viewer.refresh_from_db()
    assert viewer.role == "editor"


# --- Admin change form --------------------------------------------------------


def test_admin_demote_last_owner_form_error(admin_client: Client, membership: Membership) -> None:
    response = admin_client.post(
        _change_url(membership), _membership_post_data(membership, "editor")
    )
    assert response.status_code == 200
    assert LAST_OWNER_MESSAGE in response.content.decode()
    membership.refresh_from_db()
    assert membership.role == "owner"


def test_admin_demote_with_second_owner_succeeds(
    admin_client: Client, membership: Membership, organization: Organization
) -> None:
    _owner("bob", organization)
    response = admin_client.post(
        _change_url(membership), _membership_post_data(membership, "editor")
    )
    assert response.status_code == 302
    membership.refresh_from_db()
    assert membership.role == "editor"


# --- Admin membership delete --------------------------------------------------


def test_admin_delete_last_owner_membership_blocked(
    admin_client: Client, membership: Membership
) -> None:
    url = _delete_url("membership", membership.pk)
    get_response = admin_client.get(url)
    assert get_response.status_code == 200
    assert get_response.context["protected"]
    admin_client.post(url, {"post": "yes"})
    assert Membership.objects.filter(pk=membership.pk).exists()


def test_admin_delete_membership_with_second_owner_succeeds(
    admin_client: Client, membership: Membership, organization: Organization
) -> None:
    _owner("bob", organization)
    response = admin_client.post(_delete_url("membership", membership.pk), {"post": "yes"})
    assert response.status_code == 302
    assert not Membership.objects.filter(pk=membership.pk).exists()


def test_admin_bulk_delete_all_owners_blocked(
    admin_client: Client, membership: Membership, organization: Organization
) -> None:
    second = _owner("bob", organization)
    response = admin_client.post(
        _changelist_url("membership"),
        {
            "action": "delete_selected",
            "_selected_action": [membership.pk, second.pk],
            "post": "yes",
        },
    )
    assert response.status_code == 200
    assert Membership.objects.filter(pk__in=[membership.pk, second.pk]).count() == 2


def test_admin_bulk_delete_one_of_two_owners_succeeds(
    admin_client: Client, membership: Membership, organization: Organization
) -> None:
    second = _owner("bob", organization)
    response = admin_client.post(
        _changelist_url("membership"),
        {
            "action": "delete_selected",
            "_selected_action": [membership.pk],
            "post": "yes",
        },
    )
    assert response.status_code == 302
    assert not Membership.objects.filter(pk=membership.pk).exists()
    assert Membership.objects.filter(pk=second.pk).exists()


# --- Admin user delete --------------------------------------------------------


def test_admin_delete_sole_owner_user_blocked(
    admin_client: Client, user: User, membership: Membership
) -> None:
    url = _delete_url("user", user.pk)
    get_response = admin_client.get(url)
    assert get_response.status_code == 200
    assert get_response.context["protected"]
    admin_client.post(url, {"post": "yes"})
    assert User.objects.filter(pk=user.pk).exists()
    assert Membership.objects.filter(pk=membership.pk).exists()


def test_admin_delete_co_owner_user_succeeds(
    admin_client: Client, user: User, membership: Membership, organization: Organization
) -> None:
    _owner("bob", organization)
    response = admin_client.post(_delete_url("user", user.pk), {"post": "yes"})
    assert response.status_code == 302
    assert not User.objects.filter(pk=user.pk).exists()
    assert not Membership.objects.filter(pk=membership.pk).exists()
    assert Membership.objects.filter(organization=organization).count() == 1


# --- Organization delete still cascades ---------------------------------------


def test_admin_delete_organization_cascades(
    admin_client: Client, organization: Organization, membership: Membership
) -> None:
    response = admin_client.post(_delete_url("organization", organization.pk), {"post": "yes"})
    assert response.status_code == 302
    assert not Organization.objects.filter(pk=organization.pk).exists()
    assert not Membership.objects.filter(pk=membership.pk).exists()
