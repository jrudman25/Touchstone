"""Field validation, DB constraints, ScorerConfig params, and tenant moves."""

import pytest
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction

from records.accounts.models import Membership, Organization, User
from records.projects.models import Dataset, Project, PromptTemplate
from records.providers.models import ModelConfig, ProviderConfig, ScorerConfig

pytestmark = pytest.mark.django_db

VALID_HEX = "a1b2c3d4e5f6a7b8c9d0e1f2"


def _errors_for(excinfo: pytest.ExceptionInfo[ValidationError], field: str) -> bool:
    return field in excinfo.value.error_dict


# --- Project.baseline_run_id -------------------------------------------------


def test_baseline_run_id_valid_hex_accepted(project: Project) -> None:
    project.baseline_run_id = VALID_HEX
    project.full_clean()
    project.save()
    project.refresh_from_db()
    assert project.baseline_run_id == VALID_HEX


def test_baseline_run_id_null_accepted(project: Project) -> None:
    project.baseline_run_id = None
    project.full_clean()


@pytest.mark.parametrize(
    "bad",
    [
        "A1B2C3D4E5F6A7B8C9D0E1F2",  # uppercase
        "a1b2c3d4e5f6a7b8c9d0e1f",  # 23 chars
        "a1b2c3d4e5f6a7b8c9d0e1f2ff",  # 26 chars
        "z1b2c3d4e5f6a7b8c9d0e1f2",  # non-hex char
        "not-a-mongo-object-id-xx",  # 24 chars, not hex
    ],
)
def test_baseline_run_id_invalid_rejected_by_full_clean(project: Project, bad: str) -> None:
    project.baseline_run_id = bad
    with pytest.raises(ValidationError) as excinfo:
        project.full_clean()
    assert _errors_for(excinfo, "baseline_run_id")


def test_baseline_run_id_db_constraint(organization: Organization) -> None:
    with transaction.atomic(), pytest.raises(IntegrityError):
        Project.objects.create(organization=organization, name="bad", baseline_run_id="nothex")


# --- ProviderConfig -----------------------------------------------------------


def test_mock_provider_without_base_url_ok(organization: Organization) -> None:
    ProviderConfig(organization=organization, name="m", kind="mock").full_clean()


def test_mock_provider_with_base_url_rejected(organization: Organization) -> None:
    provider = ProviderConfig(
        organization=organization,
        name="m",
        kind="mock",
        base_url="http://localhost:11434",
    )
    with pytest.raises(ValidationError) as excinfo:
        provider.full_clean()
    assert _errors_for(excinfo, "base_url")


@pytest.mark.parametrize("kind", ["ollama", "openai_compatible"])
def test_networked_provider_requires_base_url(organization: Organization, kind: str) -> None:
    provider = ProviderConfig(organization=organization, name="n", kind=kind, base_url="")
    with pytest.raises(ValidationError) as excinfo:
        provider.full_clean()
    assert _errors_for(excinfo, "base_url")


@pytest.mark.parametrize("kind", ["ollama", "openai_compatible"])
def test_networked_provider_with_base_url_ok(organization: Organization, kind: str) -> None:
    ProviderConfig(
        organization=organization, name="n", kind=kind, base_url="http://example.com"
    ).full_clean()


def test_base_url_db_constraint_rejects_bad_pairs(organization: Organization) -> None:
    with transaction.atomic(), pytest.raises(IntegrityError):
        ProviderConfig.objects.create(
            organization=organization,
            name="m",
            kind="mock",
            base_url="http://example.com",
        )
    with transaction.atomic(), pytest.raises(IntegrityError):
        ProviderConfig.objects.create(
            organization=organization, name="o", kind="ollama", base_url=""
        )


@pytest.mark.parametrize("name", ["VALID_NAME", "v", "_X9", "OPENAI_API_KEY"])
def test_api_key_env_valid_names(organization: Organization, name: str) -> None:
    ProviderConfig(organization=organization, name="m", kind="mock", api_key_env=name).full_clean()


@pytest.mark.parametrize("name", ["1BAD", "HAS-DASH", "has space", "has.dot"])
def test_api_key_env_invalid_names(organization: Organization, name: str) -> None:
    provider = ProviderConfig(organization=organization, name="m", kind="mock", api_key_env=name)
    with pytest.raises(ValidationError) as excinfo:
        provider.full_clean()
    assert _errors_for(excinfo, "api_key_env")


# --- ScorerConfig.params -------------------------------------------------------


def _judge_params(model_config: ModelConfig, **overrides: object) -> dict[str, object]:
    params: dict[str, object] = {
        "rubric": "rubric text",
        "judge_prompt": "judge prompt",
        "judge_model_config_id": model_config.pk,
    }
    params.update(overrides)
    return params


@pytest.mark.parametrize("kind", ["exact", "contains", "regex"])
def test_rule_scorers_accept_empty_params(project: Project, kind: str) -> None:
    ScorerConfig(project=project, name="s", kind=kind, params={}).full_clean()


@pytest.mark.parametrize("kind", ["exact", "contains", "regex"])
def test_rule_scorers_reject_non_empty_params(project: Project, kind: str) -> None:
    scorer = ScorerConfig(project=project, name="s", kind=kind, params={"x": 1})
    with pytest.raises(ValidationError) as excinfo:
        scorer.full_clean()
    assert _errors_for(excinfo, "params")


def test_judge_params_valid(project: Project, model_config: ModelConfig) -> None:
    scorer = ScorerConfig(
        project=project, name="j", kind="llm_judge", params=_judge_params(model_config)
    )
    scorer.full_clean()


def test_judge_params_unknown_key_named(project: Project, model_config: ModelConfig) -> None:
    scorer = ScorerConfig(
        project=project,
        name="j",
        kind="llm_judge",
        params=_judge_params(model_config, bogus=1),
    )
    with pytest.raises(ValidationError) as excinfo:
        scorer.full_clean()
    assert _errors_for(excinfo, "params")
    assert "bogus" in str(excinfo.value)


def test_judge_params_missing_key_named(project: Project, model_config: ModelConfig) -> None:
    params = _judge_params(model_config)
    del params["rubric"]
    scorer = ScorerConfig(project=project, name="j", kind="llm_judge", params=params)
    with pytest.raises(ValidationError) as excinfo:
        scorer.full_clean()
    assert "rubric" in str(excinfo.value)


@pytest.mark.parametrize(
    "field,bad",
    [
        ("rubric", ""),
        ("rubric", "   "),
        ("rubric", 5),
        ("judge_prompt", ""),
        ("judge_prompt", None),
    ],
)
def test_judge_params_bad_strings(
    project: Project, model_config: ModelConfig, field: str, bad: object
) -> None:
    scorer = ScorerConfig(
        project=project,
        name="j",
        kind="llm_judge",
        params=_judge_params(model_config, **{field: bad}),
    )
    with pytest.raises(ValidationError) as excinfo:
        scorer.full_clean()
    assert _errors_for(excinfo, "params")


@pytest.mark.parametrize("bad_id", ["1", 1.5, True, [1], {"id": 1}])
def test_judge_model_config_id_wrong_types(
    project: Project, model_config: ModelConfig, bad_id: object
) -> None:
    scorer = ScorerConfig(
        project=project,
        name="j",
        kind="llm_judge",
        params=_judge_params(model_config, judge_model_config_id=bad_id),
    )
    with pytest.raises(ValidationError) as excinfo:
        scorer.full_clean()
    assert _errors_for(excinfo, "params")


def test_judge_model_config_id_nonexistent(project: Project, model_config: ModelConfig) -> None:
    scorer = ScorerConfig(
        project=project,
        name="j",
        kind="llm_judge",
        params=_judge_params(model_config, judge_model_config_id=999999),
    )
    with pytest.raises(ValidationError) as excinfo:
        scorer.full_clean()
    assert _errors_for(excinfo, "params")


def test_judge_scorer_without_project_raises_field_error(
    model_config: ModelConfig,
) -> None:
    scorer = ScorerConfig(
        project=None, name="j", kind="llm_judge", params=_judge_params(model_config)
    )
    with pytest.raises(ValidationError) as excinfo:
        scorer.full_clean()
    assert "project" in excinfo.value.error_dict


def test_rule_scorer_without_project_raises_field_error() -> None:
    scorer = ScorerConfig(project=None, name="s", kind="exact", params={})
    with pytest.raises(ValidationError) as excinfo:
        scorer.full_clean()
    assert "project" in excinfo.value.error_dict


def test_judge_model_in_other_org_rejected(
    project: Project, other_org_model_config: ModelConfig
) -> None:
    scorer = ScorerConfig(
        project=project,
        name="j",
        kind="llm_judge",
        params=_judge_params(other_org_model_config),
    )
    with pytest.raises(ValidationError) as excinfo:
        scorer.full_clean()
    assert _errors_for(excinfo, "params")


# --- Tenant moves --------------------------------------------------------------


def test_project_org_change_rejected(project: Project, other_organization: Organization) -> None:
    project.organization = other_organization
    with pytest.raises(ValidationError) as excinfo:
        project.full_clean()
    assert _errors_for(excinfo, "organization")


def test_provider_org_change_rejected(
    provider: ProviderConfig, other_organization: Organization
) -> None:
    provider.organization = other_organization
    with pytest.raises(ValidationError) as excinfo:
        provider.full_clean()
    assert _errors_for(excinfo, "organization")


def test_model_config_cross_org_reparent_rejected(
    model_config: ModelConfig, other_provider: ProviderConfig
) -> None:
    model_config.provider = other_provider
    with pytest.raises(ValidationError) as excinfo:
        model_config.full_clean()
    assert _errors_for(excinfo, "provider")


def test_model_config_same_org_reparent_allowed(
    model_config: ModelConfig, same_org_provider: ProviderConfig
) -> None:
    model_config.provider = same_org_provider
    model_config.full_clean()
    model_config.save()
    assert model_config.provider_id == same_org_provider.pk


def test_prompt_template_same_org_reparent_allowed(
    template: PromptTemplate, same_org_project: Project
) -> None:
    template.project = same_org_project
    template.full_clean()
    template.save()
    assert template.project_id == same_org_project.pk


def test_prompt_template_cross_org_reparent_rejected(
    template: PromptTemplate, other_project: Project
) -> None:
    template.project = other_project
    with pytest.raises(ValidationError) as excinfo:
        template.full_clean()
    assert _errors_for(excinfo, "project")


def test_scorer_same_org_reparent_allowed(
    project: Project, same_org_project: Project, model_config: ModelConfig
) -> None:
    scorer = ScorerConfig.objects.create(project=project, name="s", kind="exact", params={})
    scorer.project = same_org_project
    scorer.full_clean()
    scorer.save()
    assert scorer.project_id == same_org_project.pk


def test_membership_unique_constraint(
    membership: Membership, user: User, organization: Organization
) -> None:
    with pytest.raises(IntegrityError):
        Membership.objects.create(user=user, organization=organization, role="viewer")


def test_membership_duplicate_full_clean(
    membership: Membership, user: User, organization: Organization
) -> None:
    duplicate = Membership(user=user, organization=organization, role="editor")
    with pytest.raises(ValidationError):
        duplicate.full_clean()


def test_dataset_same_org_reparent_allowed(dataset: Dataset, same_org_project: Project) -> None:
    dataset.project = same_org_project
    dataset.full_clean()
    dataset.save()
    assert dataset.project_id == same_org_project.pk


def test_membership_role_change_allowed(membership: Membership) -> None:
    membership.role = "editor"
    membership.full_clean()
    membership.save()
    membership.refresh_from_db()
    assert membership.role == "editor"


def test_membership_user_immutable(membership: Membership, organization: Organization) -> None:
    other_user = User.objects.create_user(username="bob", password="pw-12345")
    membership.user = other_user
    with pytest.raises(ValidationError) as excinfo:
        membership.full_clean()
    assert _errors_for(excinfo, "user")


def test_membership_org_immutable(membership: Membership, other_organization: Organization) -> None:
    membership.organization = other_organization
    with pytest.raises(ValidationError) as excinfo:
        membership.full_clean()
    assert _errors_for(excinfo, "organization")
