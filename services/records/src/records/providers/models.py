"""ProviderConfig, ModelConfig, and ScorerConfig models."""

from decimal import Decimal
from typing import Any

from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator, RegexValidator
from django.db import models
from django.db.models import Q

from records.tenancy import enforce_immutable_fk, enforce_same_org_fk

ENV_NAME_RE = r"^[A-Za-z_][A-Za-z0-9_]*$"
env_name_validator = RegexValidator(
    ENV_NAME_RE, message="Must be a valid environment variable name."
)


class ProviderConfig(models.Model):
    """Connection and rate-limit settings for one LLM provider."""

    class Kind(models.TextChoices):
        MOCK = "mock", "Mock"
        OLLAMA = "ollama", "Ollama"
        OPENAI_COMPATIBLE = "openai_compatible", "OpenAI-compatible"

    NETWORKED_KINDS = frozenset({Kind.OLLAMA, Kind.OPENAI_COMPATIBLE})

    organization = models.ForeignKey(
        "accounts.Organization", on_delete=models.CASCADE, related_name="provider_configs"
    )
    name = models.CharField(max_length=255)
    kind = models.CharField(max_length=20, choices=Kind.choices)
    base_url = models.URLField(blank=True, default="")
    api_key_env = models.CharField(
        max_length=255,
        blank=True,
        default="",
        validators=[env_name_validator],
        help_text="Name of the environment variable holding the API key; never the key itself.",
    )
    max_concurrency = models.PositiveIntegerField(default=1, validators=[MinValueValidator(1)])
    requests_per_minute = models.PositiveIntegerField(
        null=True, blank=True, validators=[MinValueValidator(1)]
    )

    class Meta:
        constraints = [  # noqa: RUF012
            models.CheckConstraint(
                condition=Q(kind="mock", base_url="")
                | (Q(kind__in=["ollama", "openai_compatible"]) & ~Q(base_url="")),
                name="providerconfig_base_url_matches_kind",
            ),
        ]

    def clean(self) -> None:
        super().clean()
        # Tenant moves are forbidden: a provider never changes organizations.
        enforce_immutable_fk(self, "organization")
        if self.kind == self.Kind.MOCK:
            if self.base_url:
                raise ValidationError({"base_url": "base_url must be blank for mock providers."})
        elif self.kind in self.NETWORKED_KINDS and not self.base_url:
            raise ValidationError({"base_url": f"base_url is required for {self.kind} providers."})

    def __str__(self) -> str:
        return f"{self.name} ({self.kind})"


class ModelConfig(models.Model):
    """Generation settings and pricing for one model on a provider."""

    provider = models.ForeignKey(
        ProviderConfig, on_delete=models.CASCADE, related_name="model_configs"
    )
    model_name = models.CharField(max_length=255)
    temperature = models.FloatField(
        default=0, validators=[MinValueValidator(0), MaxValueValidator(2)]
    )
    max_tokens = models.PositiveIntegerField(validators=[MinValueValidator(1)])
    context_length = models.PositiveIntegerField(validators=[MinValueValidator(1)])
    input_price_per_1k = models.DecimalField(
        max_digits=12, decimal_places=6, default=0, validators=[MinValueValidator(Decimal(0))]
    )
    output_price_per_1k = models.DecimalField(
        max_digits=12, decimal_places=6, default=0, validators=[MinValueValidator(Decimal(0))]
    )

    def clean(self) -> None:
        super().clean()
        enforce_same_org_fk(self, "provider")

    def __str__(self) -> str:
        return f"{self.provider}: {self.model_name}"


class ScorerConfig(models.Model):
    """Scoring rule or LLM-judge settings, scoped to a project."""

    class Kind(models.TextChoices):
        EXACT = "exact", "Exact match"
        CONTAINS = "contains", "Contains"
        REGEX = "regex", "Regex"
        LLM_JUDGE = "llm_judge", "LLM judge"

    RULE_KINDS = frozenset({Kind.EXACT, Kind.CONTAINS, Kind.REGEX})
    JUDGE_PARAM_KEYS = frozenset({"rubric", "judge_prompt", "judge_model_config_id"})

    project = models.ForeignKey(
        "projects.Project", on_delete=models.CASCADE, related_name="scorer_configs"
    )
    name = models.CharField(max_length=255)
    kind = models.CharField(max_length=20, choices=Kind.choices)
    params = models.JSONField(default=dict, blank=True)

    def clean(self) -> None:
        super().clean()
        enforce_same_org_fk(self, "project")
        if self.kind in self.RULE_KINDS:
            if self.params != {}:
                raise ValidationError(
                    {"params": f"{self.kind} scorers take no params (expected {{}})."}
                )
        elif self.kind == self.Kind.LLM_JUDGE:
            self._clean_judge_params()

    def _clean_judge_params(self) -> None:
        if not isinstance(self.params, dict):
            raise ValidationError({"params": "llm_judge params must be an object."})
        keys = set(self.params)
        unknown = keys - self.JUDGE_PARAM_KEYS
        if unknown:
            raise ValidationError(
                {"params": f"Unknown llm_judge params: {', '.join(sorted(unknown))}."}
            )
        missing = self.JUDGE_PARAM_KEYS - keys
        if missing:
            raise ValidationError(
                {"params": f"Missing llm_judge params: {', '.join(sorted(missing))}."}
            )
        for key in ("rubric", "judge_prompt"):
            if not isinstance(self.params[key], str) or not self.params[key].strip():
                raise ValidationError({"params": f"{key} must be a non-empty string."})
        judge_id: Any = self.params["judge_model_config_id"]
        if isinstance(judge_id, bool) or not isinstance(judge_id, int):
            raise ValidationError({"params": "judge_model_config_id must be an integer."})
        judge = ModelConfig.objects.filter(pk=judge_id).select_related("provider").first()
        if judge is None:
            raise ValidationError({"params": f"judge_model_config_id {judge_id} does not exist."})
        if self.project_id is None:
            # Field validation reports the missing project; the org comparison
            # cannot run without one.
            return
        if judge.provider.organization_id != self.project.organization_id:
            raise ValidationError(
                {"params": "The judge model must belong to the scorer's organization."}
            )

    def __str__(self) -> str:
        return f"{self.project}: {self.name} ({self.kind})"
