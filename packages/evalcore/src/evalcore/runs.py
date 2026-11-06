"""Run and result document shapes shared by FastAPI and the worker.

ObjectIds are carried as hex strings here; conversion to/from MongoDB
``ObjectId`` happens in the persistence layer built later.
"""

from datetime import datetime
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel

from evalcore.scorers import Score


class RunStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    FINISHED = "finished"
    FAILED = "failed"
    CANCELLED = "cancelled"


TERMINAL_STATUSES = frozenset({RunStatus.FINISHED, RunStatus.FAILED, RunStatus.CANCELLED})


class PromptSnapshot(BaseModel):
    prompt_version_id: int
    template_id: int
    number: int
    system_message: str
    body: str
    variables: list[str]


class ModelSnapshot(BaseModel):
    model_config_id: int
    provider_id: int
    provider_name: str
    provider_kind: Literal["mock", "ollama", "openai_compatible"]
    model_name: str
    temperature: float
    max_tokens: int
    context_length: int
    input_price_per_1k: float
    output_price_per_1k: float
    max_concurrency: int
    requests_per_minute: int | None
    base_url: str
    api_key_env: str
    digest: str | None


class ScorerSnapshot(BaseModel):
    scorer_id: int
    name: str
    kind: Literal["exact", "contains", "regex", "llm_judge"]
    params: dict[str, str | int | float | bool]


class RunSnapshot(BaseModel):
    prompt: PromptSnapshot
    models: list[ModelSnapshot]
    scorers: list[ScorerSnapshot]
    seed: int


class RunTotals(BaseModel):
    rows: int = 0
    done: int = 0
    failed: int = 0


class ModelSummary(BaseModel):
    mean_score: float | None
    by_scorer: dict[str, float | None]
    p95_latency_ms: int | None
    cost_usd: float
    error_count: int


class Run(BaseModel):
    id: str
    organization_id: int
    project_id: int
    prompt_version_id: int
    dataset_id: int
    model_config_ids: list[int]
    scorer_ids: list[int]
    snapshot: RunSnapshot
    status: RunStatus
    created_by: int
    created_at: datetime
    finished_at: datetime | None
    totals: RunTotals
    summary: dict[str, ModelSummary]
    error: str | None = None


class Usage(BaseModel):
    input_tokens: int
    output_tokens: int


class Result(BaseModel):
    id: str
    run_id: str
    row_index: int
    model_config_id: int
    input: dict[str, str | int | float | bool]
    expected: str | None
    rendered_prompt: str
    output: str | None
    usage: Usage | None
    latency_ms: int | None
    cost_usd: float | None
    error: str | None
    context_limited: bool
    scores: list[Score]


def compute_cost(usage: Usage, model: ModelSnapshot) -> float:
    """Cost in USD from token usage and the model's per-1k prices."""
    return (
        usage.input_tokens / 1000 * model.input_price_per_1k
        + usage.output_tokens / 1000 * model.output_price_per_1k
    )


def is_context_limited(usage: Usage, model: ModelSnapshot) -> bool:
    """True when the call reached the configured context window."""
    return usage.input_tokens + usage.output_tokens >= model.context_length
