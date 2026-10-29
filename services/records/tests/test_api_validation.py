"""API-level model rules: tenant moves, scorer params, provider base_url."""

import pytest
from rest_framework.test import APIClient

from records.accounts.models import Organization
from records.projects.models import Dataset, Project, PromptTemplate
from records.providers.models import ModelConfig, ProviderConfig, ScorerConfig

pytestmark = pytest.mark.django_db

BASE = "/api/records"


def _judge_params(model_config: ModelConfig, **overrides: object) -> dict[str, object]:
    params: dict[str, object] = {
        "rubric": "rubric text",
        "judge_prompt": "judge prompt",
        "judge_model_config_id": model_config.pk,
    }
    params.update(overrides)
    return params


# --- tenant moves ----------------------------------------------------------------


def test_project_organization_move_is_400(
    dual_editor_client: APIClient,
    project: Project,
    organization: Organization,
    other_organization: Organization,
) -> None:
    response = dual_editor_client.patch(
        f"{BASE}/projects/{project.pk}/",
        {"organization": other_organization.pk},
        format="json",
    )
    assert response.status_code == 400
    project.refresh_from_db()
    assert project.organization_id == organization.pk


def test_judge_model_config_repoint_to_foreign_provider_is_400(
    dual_editor_client: APIClient,
    project: Project,
    model_config: ModelConfig,
    provider: ProviderConfig,
    other_provider: ProviderConfig,
) -> None:
    scorer = ScorerConfig.objects.create(
        project=project,
        name="judge",
        kind="llm_judge",
        params=_judge_params(model_config),
    )
    response = dual_editor_client.patch(
        f"{BASE}/models/{model_config.pk}/",
        {"provider": other_provider.pk},
        format="json",
    )
    assert response.status_code == 400
    model_config.refresh_from_db()
    assert model_config.provider_id == provider.pk
    scorer.refresh_from_db()
    assert scorer.params["judge_model_config_id"] == model_config.pk


def test_model_same_org_reparent_ok(
    owner_client: APIClient,
    model_config: ModelConfig,
    same_org_provider: ProviderConfig,
) -> None:
    response = owner_client.patch(
        f"{BASE}/models/{model_config.pk}/",
        {"provider": same_org_provider.pk},
        format="json",
    )
    assert response.status_code == 200, response.json()
    model_config.refresh_from_db()
    assert model_config.provider_id == same_org_provider.pk


def test_template_same_org_reparent_ok(
    owner_client: APIClient, template: PromptTemplate, same_org_project: Project
) -> None:
    response = owner_client.patch(
        f"{BASE}/prompt-templates/{template.pk}/",
        {"project": same_org_project.pk},
        format="json",
    )
    assert response.status_code == 200, response.json()
    template.refresh_from_db()
    assert template.project_id == same_org_project.pk


def test_dataset_same_org_reparent_ok(
    owner_client: APIClient, dataset: Dataset, same_org_project: Project
) -> None:
    response = owner_client.patch(
        f"{BASE}/datasets/{dataset.pk}/",
        {"project": same_org_project.pk},
        format="json",
    )
    assert response.status_code == 200, response.json()
    dataset.refresh_from_db()
    assert dataset.project_id == same_org_project.pk


# --- ScorerConfig.params ------------------------------------------------------------


def _create_scorer(
    client: APIClient, project: Project, kind: str, params: dict[str, object]
) -> int:
    return client.post(
        f"{BASE}/scorers/",
        {"project": project.pk, "name": "s", "kind": kind, "params": params},
        format="json",
    ).status_code


def test_exact_scorer_empty_params_ok(owner_client: APIClient, project: Project) -> None:
    assert _create_scorer(owner_client, project, "exact", {}) == 201


def test_exact_scorer_non_empty_params_is_400(owner_client: APIClient, project: Project) -> None:
    assert _create_scorer(owner_client, project, "exact", {"x": 1}) == 400


def test_judge_scorer_valid_params_ok(
    owner_client: APIClient, project: Project, model_config: ModelConfig
) -> None:
    assert _create_scorer(owner_client, project, "llm_judge", _judge_params(model_config)) == 201


def test_judge_scorer_missing_key_is_400(
    owner_client: APIClient, project: Project, model_config: ModelConfig
) -> None:
    params = _judge_params(model_config)
    del params["rubric"]
    assert _create_scorer(owner_client, project, "llm_judge", params) == 400


def test_judge_scorer_unknown_key_is_400(
    owner_client: APIClient, project: Project, model_config: ModelConfig
) -> None:
    params = _judge_params(model_config, bogus=1)
    assert _create_scorer(owner_client, project, "llm_judge", params) == 400


def test_judge_scorer_foreign_model_is_400(
    owner_client: APIClient,
    project: Project,
    other_org_model_config: ModelConfig,
) -> None:
    params = _judge_params(other_org_model_config)
    assert _create_scorer(owner_client, project, "llm_judge", params) == 400


# --- ProviderConfig.base_url ---------------------------------------------------------


def _create_provider(
    client: APIClient, organization: Organization, kind: str, base_url: str
) -> int:
    return client.post(
        f"{BASE}/providers/",
        {
            "organization": organization.pk,
            "name": "p",
            "kind": kind,
            "base_url": base_url,
        },
        format="json",
    ).status_code


def test_mock_provider_with_base_url_is_400(
    owner_client: APIClient, organization: Organization
) -> None:
    assert _create_provider(owner_client, organization, "mock", "http://localhost:11434") == 400


def test_ollama_provider_without_base_url_is_400(
    owner_client: APIClient, organization: Organization
) -> None:
    assert _create_provider(owner_client, organization, "ollama", "") == 400


def test_ollama_provider_with_base_url_ok(
    owner_client: APIClient, organization: Organization
) -> None:
    assert _create_provider(owner_client, organization, "ollama", "http://localhost:11434") == 201


def test_mock_provider_blank_base_url_ok(
    owner_client: APIClient, organization: Organization
) -> None:
    assert _create_provider(owner_client, organization, "mock", "") == 201


# --- Dataset.row_count ----------------------------------------------------------------


def test_dataset_row_count_is_read_only(owner_client: APIClient, project: Project) -> None:
    response = owner_client.post(
        f"{BASE}/datasets/",
        {"project": project.pk, "name": "d", "row_count": 5},
        format="json",
    )
    assert response.status_code == 201
    dataset = Dataset.objects.get(pk=response.json()["id"])
    assert dataset.row_count is None

    response = owner_client.patch(f"{BASE}/datasets/{dataset.pk}/", {"row_count": 7}, format="json")
    assert response.status_code == 200
    dataset.refresh_from_db()
    assert dataset.row_count is None


# --- baseline_run_id --------------------------------------------------------------------


def test_project_baseline_run_id_validated(owner_client: APIClient, project: Project) -> None:
    response = owner_client.patch(
        f"{BASE}/projects/{project.pk}/",
        {"baseline_run_id": "a1b2c3d4e5f6a7b8c9d0e1f2"},
        format="json",
    )
    assert response.status_code == 200
    response = owner_client.patch(
        f"{BASE}/projects/{project.pk}/",
        {"baseline_run_id": "not-hex"},
        format="json",
    )
    assert response.status_code == 400
    project.refresh_from_db()
    assert project.baseline_run_id == "a1b2c3d4e5f6a7b8c9d0e1f2"
