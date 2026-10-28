"""Auth endpoint tests: obtain, refresh rotation, logout, and bearer rules."""

import json
from datetime import timedelta
from typing import Any

import jwt
import pytest
from django.conf import settings
from django.test import Client
from rest_framework_simplejwt.token_blacklist.models import (
    BlacklistedToken,
    OutstandingToken,
)
from rest_framework_simplejwt.tokens import AccessToken

from evalcore import (
    AccessClaims,
    InvalidAccessTokenError,
    Role,
    verify_access_token,
)
from records.accounts.models import Membership, Organization, User

pytestmark = pytest.mark.django_db

TOKEN_URL = "/api/records/auth/token/"
REFRESH_URL = "/api/records/auth/token/refresh/"
LOGOUT_URL = "/api/records/auth/logout/"
ME_URL = "/api/records/auth/me/"
COOKIE = "touchstone_refresh"


def _obtain(client: Client, username: str = "alice", password: str = "pw-12345") -> Any:
    return client.post(
        TOKEN_URL,
        data=json.dumps({"username": username, "password": password}),
        content_type="application/json",
    )


def _refresh(client: Client, header: str | None = "1") -> Any:
    if header is None:
        return client.post(REFRESH_URL)
    return client.post(REFRESH_URL, headers={"X-Auth-Refresh": header})


def _refresh_jti(raw_refresh: str) -> str:
    return str(jwt.decode(raw_refresh, settings.JWT_PUBLIC_KEY, algorithms=["RS256"])["jti"])


def _cookie_value(client: Client) -> str:
    return str(client.cookies[COOKIE].value)


# --- obtain -------------------------------------------------------------------


def test_obtain_returns_access_and_refresh_cookie(client: Client, user: User) -> None:
    response = _obtain(client)
    assert response.status_code == 200
    assert set(response.json()) == {"access"}

    cookie = response.cookies[COOKIE]
    assert cookie.value
    assert cookie["httponly"]
    assert cookie["samesite"] == "Strict"
    assert cookie["secure"]
    assert cookie["path"] == "/api/records/auth/"
    assert cookie["max-age"] == 7 * 24 * 3600


def test_obtain_cookie_not_secure_when_setting_off(
    client: Client, user: User, settings: Any
) -> None:
    settings.AUTH_COOKIE_SECURE = False
    response = _obtain(client)
    assert response.status_code == 200
    assert not response.cookies[COOKIE]["secure"]


@pytest.mark.parametrize(
    "body",
    [
        [],  # JSON array
        "hello",  # JSON string
        {"username": ["a"], "password": {"p": 1}},  # non-string fields
        {"username": "alice"},  # missing password
    ],
)
def test_obtain_malformed_body_400_no_cookie(client: Client, user: User, body: object) -> None:
    response = client.post(TOKEN_URL, data=json.dumps(body), content_type="application/json")
    assert response.status_code == 400
    assert COOKIE not in response.cookies


def test_obtain_bad_password_401_no_cookie(client: Client, user: User) -> None:
    response = _obtain(client, password="wrong")
    assert response.status_code == 401
    assert COOKIE not in response.cookies


def test_obtain_inactive_user_401(client: Client, user: User) -> None:
    user.is_active = False
    user.save()
    response = _obtain(client)
    assert response.status_code == 401
    assert COOKIE not in response.cookies


# --- refresh ------------------------------------------------------------------


def test_refresh_without_header_403_no_blacklist(
    client: Client, user: User, membership: Membership
) -> None:
    _obtain(client)
    old_raw = _cookie_value(client)
    for header in (None, "0"):
        response = _refresh(client, header=header)
        assert response.status_code == 403
    assert not BlacklistedToken.objects.filter(token__jti=_refresh_jti(old_raw)).exists()


def test_refresh_without_cookie_401(client: Client) -> None:
    client.cookies.clear()
    response = client.post(REFRESH_URL, HTTP_X_AUTH_REFRESH="1")
    assert response.status_code == 401


def test_refresh_rotates_and_blacklists(client: Client, user: User, membership: Membership) -> None:
    obtain = _obtain(client)
    old_access = obtain.json()["access"]
    old_raw = _cookie_value(client)

    response = _refresh(client)
    assert response.status_code == 200
    new_access = response.json()["access"]
    assert new_access != old_access
    new_raw = _cookie_value(client)
    assert new_raw != old_raw

    assert BlacklistedToken.objects.filter(token__jti=_refresh_jti(old_raw)).exists()

    # Reusing the old refresh token is rejected and the cookie is cleared.
    client.cookies[COOKIE] = old_raw
    reuse = client.post(REFRESH_URL, HTTP_X_AUTH_REFRESH="1")
    assert reuse.status_code == 401
    cleared = reuse.cookies[COOKIE]
    assert cleared.value == ""
    assert cleared["max-age"] == 0
    assert cleared["path"] == "/api/records/auth/"


def test_refresh_with_garbage_cookie_401(client: Client) -> None:
    client.cookies[COOKIE] = "garbage"
    response = client.post(REFRESH_URL, HTTP_X_AUTH_REFRESH="1")
    assert response.status_code == 401
    assert response.cookies[COOKIE].value == ""


# --- logout -------------------------------------------------------------------


def test_logout_blacklists_and_clears(client: Client, user: User, membership: Membership) -> None:
    _obtain(client)
    old_raw = _cookie_value(client)
    response = client.post(LOGOUT_URL)
    assert response.status_code == 204
    cleared = response.cookies[COOKIE]
    assert cleared.value == ""
    assert cleared["max-age"] == 0
    assert cleared["path"] == "/api/records/auth/"
    assert BlacklistedToken.objects.filter(token__jti=_refresh_jti(old_raw)).exists()

    client.cookies[COOKIE] = old_raw
    assert client.post(REFRESH_URL, HTTP_X_AUTH_REFRESH="1").status_code == 401


def test_logout_without_cookie_204(client: Client) -> None:
    assert client.post(LOGOUT_URL).status_code == 204


# --- role rebuild at refresh ----------------------------------------------------


def _make_viewer(client: Client, organization: Organization) -> User:
    viewer = User.objects.create_user(username="vicky", password="pw-12345")
    Membership.objects.create(user=viewer, organization=organization, role="viewer")
    response = _obtain(client, "vicky")
    assert response.status_code == 200
    return viewer


def _verify(access: str) -> AccessClaims:
    return verify_access_token(access, settings.JWT_PUBLIC_KEY)


def test_roles_rebuilt_from_db_at_refresh(
    client: Client, organization: Organization, other_organization: Organization
) -> None:
    viewer = _make_viewer(client, organization)
    first_access = _obtain(client, "vicky").json()["access"]
    claims = _verify(first_access)
    assert claims.orgs == {organization.pk: Role.VIEWER}

    # Change role and add a second membership; the next refresh must see both.
    membership = Membership.objects.get(user=viewer, organization=organization)
    membership.role = "editor"
    membership.save()
    Membership.objects.create(user=viewer, organization=other_organization, role="viewer")
    refreshed = _refresh(client)
    assert refreshed.status_code == 200
    claims = _verify(refreshed.json()["access"])
    assert claims.orgs == {
        organization.pk: Role.EDITOR,
        other_organization.pk: Role.VIEWER,
    }

    # Deleting a membership drops the org on the next refresh.
    Membership.objects.get(user=viewer, organization=other_organization).delete()
    refreshed = _refresh(client)
    assert refreshed.status_code == 200
    claims = _verify(refreshed.json()["access"])
    assert claims.orgs == {organization.pk: Role.EDITOR}


def test_inactive_user_refresh_401(client: Client, organization: Organization) -> None:
    viewer = _make_viewer(client, organization)
    viewer.is_active = False
    viewer.save()
    response = _refresh(client)
    assert response.status_code == 401
    assert response.cookies[COOKIE].value == ""


# --- bearer authentication on /me/ ----------------------------------------------


def test_me_with_access_token(
    client: Client, user: User, membership: Membership, organization: Organization
) -> None:
    access = _obtain(client).json()["access"]
    response = client.get(ME_URL, HTTP_AUTHORIZATION=f"Bearer {access}")
    assert response.status_code == 200
    body = response.json()
    assert body["id"] == user.pk
    assert body["username"] == user.username
    assert body["organizations"] == [
        {
            "id": organization.pk,
            "name": organization.name,
            "slug": organization.slug,
            "role": "owner",
        }
    ]


def test_me_with_refresh_token_as_bearer_401(
    client: Client, user: User, membership: Membership
) -> None:
    _obtain(client)
    refresh_raw = _cookie_value(client)
    response = client.get(ME_URL, HTTP_AUTHORIZATION=f"Bearer {refresh_raw}")
    assert response.status_code == 401


def test_me_without_header_401(client: Client) -> None:
    assert client.get(ME_URL).status_code == 401


def test_me_with_expired_access_401(client: Client, user: User) -> None:
    token = AccessToken.for_user(user)
    token.set_exp(lifetime=timedelta(seconds=-10))
    response = client.get(ME_URL, HTTP_AUTHORIZATION=f"Bearer {token}")
    assert response.status_code == 401


def test_me_session_only_superuser_401(admin_client: Client) -> None:
    # Session authentication is never accepted for API bearer auth.
    assert admin_client.get(ME_URL).status_code == 401


# --- evalcore integration --------------------------------------------------------


def test_django_access_token_verified_by_evalcore(
    client: Client, user: User, membership: Membership, organization: Organization
) -> None:
    access = _obtain(client).json()["access"]
    claims = verify_access_token(access, settings.JWT_PUBLIC_KEY)
    assert claims.user_id == user.pk
    assert claims.orgs == {organization.pk: Role.OWNER}
    assert claims.has_role(organization.pk, Role.VIEWER)


def test_django_refresh_token_rejected_by_evalcore(
    client: Client, user: User, membership: Membership
) -> None:
    _obtain(client)
    refresh_raw = _cookie_value(client)
    with pytest.raises(InvalidAccessTokenError):
        verify_access_token(refresh_raw, settings.JWT_PUBLIC_KEY)

    # Still rejected after the token is blacklisted at rotation.
    _refresh(client)
    with pytest.raises(InvalidAccessTokenError):
        verify_access_token(refresh_raw, settings.JWT_PUBLIC_KEY)


def test_outstanding_token_row_created_on_obtain(
    client: Client, user: User, membership: Membership
) -> None:
    _obtain(client)
    raw = _cookie_value(client)
    assert OutstandingToken.objects.filter(jti=_refresh_jti(raw)).exists()
