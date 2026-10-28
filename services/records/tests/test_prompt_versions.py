"""Immutability, numbering, variable extraction, and PROTECT behavior."""

import threading

import pytest
from django.core.exceptions import ValidationError
from django.db import IntegrityError, connections
from django.db.models import ProtectedError

from records.accounts.models import Organization
from records.projects.managers import ImmutableRecordError
from records.projects.models import Project, PromptTemplate, PromptVersion
from records.projects.services import create_prompt_version
from records.projects.variables import extract_variables

pytestmark = pytest.mark.django_db


@pytest.fixture
def version(template: PromptTemplate) -> PromptVersion:
    return create_prompt_version(template, system_message="sys {{ a }}", body="hi {{b}}")


def test_instance_save_of_existing_raises(version: PromptVersion) -> None:
    version.body = "changed"
    with pytest.raises(ImmutableRecordError):
        version.save()
    version.refresh_from_db()
    assert version.body == "hi {{b}}"


def test_instance_delete_raises(version: PromptVersion) -> None:
    with pytest.raises(ImmutableRecordError):
        version.delete()
    assert PromptVersion.objects.filter(pk=version.pk).exists()


def test_queryset_update_raises(version: PromptVersion) -> None:
    with pytest.raises(ImmutableRecordError):
        PromptVersion.objects.filter(pk=version.pk).update(body="x")
    version.refresh_from_db()
    assert version.body == "hi {{b}}"


def test_queryset_delete_raises(version: PromptVersion) -> None:
    with pytest.raises(ImmutableRecordError):
        PromptVersion.objects.filter(pk=version.pk).delete()
    assert PromptVersion.objects.filter(pk=version.pk).exists()


def test_bulk_update_raises(version: PromptVersion) -> None:
    version.body = "changed"
    with pytest.raises(ImmutableRecordError):
        PromptVersion.objects.bulk_update([version], ["body"])
    version.refresh_from_db()
    assert version.body == "hi {{b}}"


def test_related_manager_update_and_delete_raise(version: PromptVersion) -> None:
    with pytest.raises(ImmutableRecordError):
        version.template.versions.update(body="x")
    with pytest.raises(ImmutableRecordError):
        version.template.versions.delete()
    version.refresh_from_db()
    assert version.body == "hi {{b}}"


def test_template_delete_protected(version: PromptVersion, template: PromptTemplate) -> None:
    with pytest.raises(ProtectedError):
        template.delete()
    assert PromptVersion.objects.filter(pk=version.pk).exists()


def test_project_delete_protected(version: PromptVersion, project: Project) -> None:
    with pytest.raises(ProtectedError):
        project.delete()
    assert PromptVersion.objects.filter(pk=version.pk).exists()


def test_organization_delete_protected(version: PromptVersion, organization: Organization) -> None:
    with pytest.raises(ProtectedError):
        organization.delete()
    assert PromptVersion.objects.filter(pk=version.pk).exists()


def test_numbers_allocate_sequentially(template: PromptTemplate) -> None:
    numbers = [
        create_prompt_version(template, system_message="", body=f"b{i}").number for i in range(3)
    ]
    assert numbers == [1, 2, 3]


def test_template_number_uniqueness(template: PromptTemplate) -> None:
    create_prompt_version(template, system_message="", body="b")
    duplicate = PromptVersion(template=template, number=1, body="dup")
    with pytest.raises(IntegrityError):
        duplicate.save()


def test_extract_variables_order_and_dedup() -> None:
    assert extract_variables("{{ a }} {{b}} {{a}}", "{{c}} {{ b }}") == ["a", "b", "c"]


def test_extract_variables_skips_invalid() -> None:
    assert extract_variables("{{1x}} {{ }} {{}} {{_ok}}", "") == ["_ok"]


def test_variables_stored_at_creation(template: PromptTemplate) -> None:
    version = create_prompt_version(
        template, system_message="Hi {{user}}", body="{{ user }} says {{thing}}"
    )
    assert version.variables == ["user", "thing"]


def test_empty_body_rejected_by_full_clean(template: PromptTemplate) -> None:
    version = PromptVersion(template=template, number=9, body="")
    with pytest.raises(ValidationError):
        version.full_clean()


@pytest.mark.django_db(transaction=True)
def test_concurrent_creates_get_unique_numbers(template: PromptTemplate) -> None:
    barrier = threading.Barrier(5)
    numbers: list[int] = []
    errors: list[BaseException] = []

    def worker() -> None:
        try:
            # Open this thread's DB connection before the barrier so slow
            # connection setup happens in parallel and the barrier release
            # measures only lock-serialized version creation.
            connections["default"].ensure_connection()
            barrier.wait(timeout=60)
            created = create_prompt_version(template, system_message="", body="b")
            numbers.append(created.number)
        except BaseException as exc:
            errors.append(exc)
        finally:
            connections.close_all()

    threads = [threading.Thread(target=worker) for _ in range(5)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=120)
        assert not thread.is_alive(), "a worker thread is still running"

    assert not errors, [repr(e) for e in errors]
    assert sorted(numbers) == [1, 2, 3, 4, 5]
