"""Shared fixtures: a two-organization tenant layout and common records."""

import pytest

from records.accounts.models import Membership, Organization, User
from records.projects.models import Dataset, Project, PromptTemplate
from records.providers.models import ModelConfig, ProviderConfig


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
