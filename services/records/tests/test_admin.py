"""Admin behavior: view-only PromptVersions and tenant-move rejection."""

import json

import pytest
from django.contrib.admin.models import ADDITION, LogEntry
from django.test import Client
from django.urls import reverse

from records.accounts.models import Organization
from records.projects.models import Project, PromptTemplate, PromptVersion
from records.projects.services import create_prompt_version
from records.providers.models import ModelConfig

pytestmark = pytest.mark.django_db


@pytest.fixture
def version(template: PromptTemplate) -> PromptVersion:
    return create_prompt_version(template, system_message="sys", body="hi {{name}}")


def test_health(client: Client) -> None:
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_admin_anonymous_redirects_to_login(client: Client) -> None:
    response = client.get("/api/records/admin/")
    assert response.status_code == 302
    assert "/api/records/admin/login/" in response["Location"]


def test_version_change_page_is_read_only(admin_client: Client, version: PromptVersion) -> None:
    url = reverse("admin:projects_promptversion_change", args=[version.pk])
    response = admin_client.get(url)
    assert response.status_code == 200
    assert response.context["has_change_permission"] is False
    assert b'name="body"' not in response.content


def test_version_change_post_rejected(admin_client: Client, version: PromptVersion) -> None:
    url = reverse("admin:projects_promptversion_change", args=[version.pk])
    response = admin_client.post(
        url,
        {
            "template": version.template_id,
            "system_message": "tampered",
            "body": "tampered",
        },
    )
    assert response.status_code == 403
    version.refresh_from_db()
    assert version.body == "hi {{name}}"


def test_version_delete_rejected(admin_client: Client, version: PromptVersion) -> None:
    url = reverse("admin:projects_promptversion_delete", args=[version.pk])
    assert admin_client.get(url).status_code == 403
    assert admin_client.post(url).status_code == 403
    assert PromptVersion.objects.filter(pk=version.pk).exists()


def test_admin_add_creates_version_with_server_fields(
    admin_client: Client, template: PromptTemplate
) -> None:
    url = reverse("admin:projects_promptversion_add")
    assert admin_client.get(url).status_code == 200
    response = admin_client.post(
        url,
        {
            "template": template.pk,
            "system_message": "You are {{role}}.",
            "body": "Say hi to {{ user }}.",
        },
    )
    assert response.status_code == 302
    version = PromptVersion.objects.get(template=template)
    assert version.number == 1
    assert version.variables == ["role", "user"]
    follow = admin_client.get(response["Location"])
    assert follow.status_code == 200


def test_admin_add_writes_log_entry(admin_client: Client, template: PromptTemplate) -> None:
    url = reverse("admin:projects_promptversion_add")
    response = admin_client.post(
        url,
        {"template": template.pk, "system_message": "sys", "body": "hi {{name}}"},
    )
    assert response.status_code == 302
    version = PromptVersion.objects.get(template=template)
    assert LogEntry.objects.filter(object_id=str(version.pk), action_flag=ADDITION).exists()


def test_scorer_add_without_project_shows_form_error(
    admin_client: Client, model_config: ModelConfig
) -> None:
    url = reverse("admin:providers_scorerconfig_add")
    response = admin_client.post(
        url,
        {
            "name": "judge",
            "kind": "llm_judge",
            "params": json.dumps(
                {
                    "rubric": "r",
                    "judge_prompt": "p",
                    "judge_model_config_id": model_config.pk,
                }
            ),
        },
    )
    assert response.status_code == 200
    assert "project" in response.context["adminform"].form.errors


def test_admin_add_increments_number(
    admin_client: Client, template: PromptTemplate, version: PromptVersion
) -> None:
    url = reverse("admin:projects_promptversion_add")
    response = admin_client.post(
        url, {"template": template.pk, "system_message": "", "body": "next"}
    )
    assert response.status_code == 302
    assert PromptVersion.objects.filter(template=template).count() == 2
    newest = PromptVersion.objects.get(template=template, number=2)
    assert newest.body == "next"


def test_project_org_change_via_admin_rejected(
    admin_client: Client, project: Project, other_organization: Organization
) -> None:
    url = reverse("admin:projects_project_change", args=[project.pk])
    response = admin_client.post(
        url,
        {
            "organization": other_organization.pk,
            "name": project.name,
            "description": project.description,
            "baseline_run_id": "",
        },
    )
    assert response.status_code == 200
    assert "organization" in response.context["adminform"].form.errors
    project.refresh_from_db()
    assert project.organization_id != other_organization.pk
