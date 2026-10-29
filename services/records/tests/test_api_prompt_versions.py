"""PromptVersion API: server-assigned numbers/variables, immutability, PROTECT."""

import pytest
from rest_framework.test import APIClient

from records.projects.models import PromptTemplate, PromptVersion

pytestmark = pytest.mark.django_db

BASE = "/api/records/prompt-versions/"


def test_create_assigns_number_and_variables(
    owner_client: APIClient, template: PromptTemplate
) -> None:
    response = owner_client.post(
        BASE,
        {
            "template": template.pk,
            "system_message": "sys {{a}}",
            "body": "hi {{b}} and {{a}}",
        },
        format="json",
    )
    assert response.status_code == 201, response.json()
    body = response.json()
    assert body["number"] == 1
    assert set(body["variables"]) == {"a", "b"}
    assert body["template"] == template.pk
    assert body["created_at"]


def test_second_create_assigns_next_number(
    owner_client: APIClient, prompt_version: PromptVersion, template: PromptTemplate
) -> None:
    response = owner_client.post(BASE, {"template": template.pk, "body": "second"}, format="json")
    assert response.status_code == 201
    assert response.json()["number"] == 2


def test_client_supplied_number_and_variables_are_ignored(
    owner_client: APIClient, template: PromptTemplate
) -> None:
    response = owner_client.post(
        BASE,
        {
            "template": template.pk,
            "body": "hi {{x}}",
            "number": 99,
            "variables": ["fake"],
        },
        format="json",
    )
    assert response.status_code == 201
    body = response.json()
    assert body["number"] == 1
    assert body["variables"] == ["x"]
    version = PromptVersion.objects.get(template=template)
    assert version.number == 1
    assert version.variables == ["x"]


def test_system_message_defaults_to_blank(
    owner_client: APIClient, template: PromptTemplate
) -> None:
    response = owner_client.post(BASE, {"template": template.pk, "body": "hi"}, format="json")
    assert response.status_code == 201
    assert response.json()["system_message"] == ""


@pytest.mark.parametrize("method", ["put", "patch", "delete"])
def test_update_and_delete_are_405(
    owner_client: APIClient, prompt_version: PromptVersion, method: str
) -> None:
    response = getattr(owner_client, method)(f"{BASE}{prompt_version.pk}/", {}, format="json")
    assert response.status_code == 405
    prompt_version.refresh_from_db()
    assert prompt_version.body == "hi {{b}}"


def test_delete_template_with_version_is_409(
    owner_client: APIClient, prompt_version: PromptVersion, template: PromptTemplate
) -> None:
    response = owner_client.delete(f"/api/records/prompt-templates/{template.pk}/")
    assert response.status_code == 409
    assert PromptTemplate.objects.filter(pk=template.pk).exists()
    assert PromptVersion.objects.filter(pk=prompt_version.pk).exists()
