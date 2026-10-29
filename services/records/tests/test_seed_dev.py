"""seed_dev management command: idempotence, env requirements, upgrades."""

from io import StringIO

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

from records.accounts.models import Membership, Organization, User
from records.projects.models import Project
from records.providers.models import ModelConfig, ProviderConfig

pytestmark = pytest.mark.django_db

USERNAME = "devadmin"


def _set_credentials(monkeypatch: pytest.MonkeyPatch, password: str = "pw-first") -> None:
    monkeypatch.setenv("DEV_SUPERUSER_USERNAME", USERNAME)
    monkeypatch.setenv("DEV_SUPERUSER_PASSWORD", password)


def _seed() -> str:
    out = StringIO()
    call_command("seed_dev", stdout=out)
    return out.getvalue()


def test_seed_twice_is_idempotent(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_credentials(monkeypatch)
    _seed()
    _set_credentials(monkeypatch, password="pw-second")
    _seed()

    user = User.objects.get(username=USERNAME)
    # An existing user's password is never changed.
    assert user.check_password("pw-first")
    assert user.is_staff
    assert user.is_superuser

    organization = Organization.objects.get(slug="dev")
    assert Organization.objects.count() == 1
    assert (
        Membership.objects.filter(user=user, organization=organization, role="owner").count() == 1
    )
    assert Project.objects.filter(organization=organization).count() == 1
    assert ProviderConfig.objects.filter(organization=organization).count() == 1
    assert ModelConfig.objects.count() == 1


def test_missing_password_raises_before_touching_db(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DEV_SUPERUSER_USERNAME", USERNAME)
    monkeypatch.delenv("DEV_SUPERUSER_PASSWORD", raising=False)
    with pytest.raises(CommandError):
        call_command("seed_dev")
    assert not User.objects.exists()
    assert not Organization.objects.exists()


def test_empty_password_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DEV_SUPERUSER_USERNAME", USERNAME)
    monkeypatch.setenv("DEV_SUPERUSER_PASSWORD", "   ")
    with pytest.raises(CommandError):
        call_command("seed_dev")
    assert not User.objects.exists()


def test_missing_username_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DEV_SUPERUSER_USERNAME", raising=False)
    monkeypatch.setenv("DEV_SUPERUSER_PASSWORD", "pw-first")
    with pytest.raises(CommandError):
        call_command("seed_dev")
    assert not User.objects.exists()


def test_existing_editor_membership_is_upgraded(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_credentials(monkeypatch)
    user = User.objects.create_user(username=USERNAME, password="pw-first")
    organization = Organization.objects.create(name="Dev Organization", slug="dev")
    membership = Membership.objects.create(user=user, organization=organization, role="editor")
    output = _seed()
    membership.refresh_from_db()
    assert membership.role == "owner"
    assert "updated" in output


def test_existing_user_gets_staff_and_superuser(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_credentials(monkeypatch)
    user = User.objects.create_user(username=USERNAME, password="pw-keep")
    _seed()
    user.refresh_from_db()
    assert user.is_staff
    assert user.is_superuser
    assert user.check_password("pw-keep")
