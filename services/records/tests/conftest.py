"""Shared fixtures: a two-organization tenant layout and common records."""

from collections.abc import Callable

import pytest
from rest_framework.test import APIClient

from records.accounts.auth.tokens import build_refresh_token
from records.accounts.models import Membership, Organization, User
from records.projects.models import Dataset, Project, PromptTemplate, PromptVersion
from records.projects.services import create_prompt_version
from records.providers.models import ModelConfig, ProviderConfig, ScorerConfig


@pytest.fixture
def organization(db: object) -> Organization:
    return Organization.objects.create(name="Acme", slug="acme")


@pytest.fixture
def other_organization(db: object) -> Organization:
    return Organization.objects.create(name="Globex", slug="globex")


@pytest.fixture
def user(db: object) -> User:
    return User.objects.create_user(username="alice", password="pw-12345")


@pytest.fixture
def membership(db: object, user: User, organization: Organization) -> Membership:
    return Membership.objects.create(user=user, organization=organization, role="owner")


@pytest.fixture
def project(db: object, organization: Organization) -> Project:
    return Project.objects.create(organization=organization, name="Proj", description="d")


@pytest.fixture
def same_org_project(db: object, organization: Organization) -> Project:
    return Project.objects.create(organization=organization, name="Proj2")


@pytest.fixture
def other_project(db: object, other_organization: Organization) -> Project:
    return Project.objects.create(organization=other_organization, name="OtherProj")


@pytest.fixture
def template(db: object, project: Project) -> PromptTemplate:
    return PromptTemplate.objects.create(project=project, name="greet")


@pytest.fixture
def dataset(db: object, project: Project) -> Dataset:
    return Dataset.objects.create(project=project, name="ds")


@pytest.fixture
def provider(db: object, organization: Organization) -> ProviderConfig:
    return ProviderConfig.objects.create(organization=organization, name="mock-prov", kind="mock")


@pytest.fixture
def same_org_provider(db: object, organization: Organization) -> ProviderConfig:
    return ProviderConfig.objects.create(
        organization=organization,
        name="ollama-prov",
        kind="ollama",
        base_url="http://localhost:11434",
    )


@pytest.fixture
def other_provider(db: object, other_organization: Organization) -> ProviderConfig:
    return ProviderConfig.objects.create(
        organization=other_organization, name="other-prov", kind="mock"
    )


@pytest.fixture
def model_config(db: object, provider: ProviderConfig) -> ModelConfig:
    return ModelConfig.objects.create(
        provider=provider, model_name="mock-1", max_tokens=256, context_length=4096
    )


@pytest.fixture
def other_org_model_config(db: object, other_provider: ProviderConfig) -> ModelConfig:
    return ModelConfig.objects.create(
        provider=other_provider, model_name="other-1", max_tokens=256, context_length=4096
    )


@pytest.fixture
def other_template(db: object, other_project: Project) -> PromptTemplate:
    return PromptTemplate.objects.create(project=other_project, name="other-tpl")


@pytest.fixture
def other_version(db: object, other_template: PromptTemplate) -> PromptVersion:
    return create_prompt_version(other_template, system_message="", body="other")


@pytest.fixture
def other_dataset(db: object, other_project: Project) -> Dataset:
    return Dataset.objects.create(project=other_project, name="other-ds")


@pytest.fixture
def other_scorer(db: object, other_project: Project) -> ScorerConfig:
    return ScorerConfig.objects.create(project=other_project, name="other-s", kind="exact")


@pytest.fixture
def scorer(db: object, project: Project) -> ScorerConfig:
    return ScorerConfig.objects.create(project=project, name="s", kind="exact", params={})


@pytest.fixture
def prompt_version(db: object, template: PromptTemplate) -> PromptVersion:
    return create_prompt_version(template, system_message="sys {{a}}", body="hi {{b}}")


@pytest.fixture
def nonmember_user(db: object) -> User:
    return User.objects.create_user(username="nancy", password="pw-12345")


@pytest.fixture
def other_org_membership(db: object, other_organization: Organization) -> Membership:
    owner = User.objects.create_user(username="olga", password="pw-12345")
    return Membership.objects.create(user=owner, organization=other_organization, role="owner")


# --- API clients ---------------------------------------------------------------


def _bearer_client(user: User) -> APIClient:
    client = APIClient()
    access = build_refresh_token(user).access_token
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {access}")
    return client


@pytest.fixture
def api_client(db: object) -> APIClient:
    return APIClient()


@pytest.fixture
def bearer_client(db: object) -> Callable[[User], APIClient]:
    return _bearer_client


@pytest.fixture
def owner_client(db: object, user: User, membership: Membership) -> APIClient:
    return _bearer_client(user)


@pytest.fixture
def editor_user(db: object) -> User:
    return User.objects.create_user(username="erin", password="pw-12345")


@pytest.fixture
def editor_membership(db: object, editor_user: User, organization: Organization) -> Membership:
    return Membership.objects.create(user=editor_user, organization=organization, role="editor")


@pytest.fixture
def editor_client(db: object, editor_user: User, editor_membership: Membership) -> APIClient:
    return _bearer_client(editor_user)


@pytest.fixture
def viewer_user(db: object) -> User:
    return User.objects.create_user(username="vera", password="pw-12345")


@pytest.fixture
def viewer_membership(db: object, viewer_user: User, organization: Organization) -> Membership:
    return Membership.objects.create(user=viewer_user, organization=organization, role="viewer")


@pytest.fixture
def viewer_client(db: object, viewer_user: User, viewer_membership: Membership) -> APIClient:
    return _bearer_client(viewer_user)


@pytest.fixture
def dual_editor_user(db: object) -> User:
    return User.objects.create_user(username="dave", password="pw-12345")


@pytest.fixture
def dual_editor(
    db: object, dual_editor_user: User, organization: Organization, other_organization: Organization
) -> User:
    """An editor in both organizations, used for tenant-move tests."""
    Membership.objects.create(user=dual_editor_user, organization=organization, role="editor")
    Membership.objects.create(user=dual_editor_user, organization=other_organization, role="editor")
    return dual_editor_user


@pytest.fixture
def dual_editor_client(db: object, dual_editor: User) -> APIClient:
    return _bearer_client(dual_editor)
