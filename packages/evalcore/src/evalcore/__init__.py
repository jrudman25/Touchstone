"""Shared schemas, provider clients, scorers, Mongo helpers, and JWT verification."""

from evalcore.access_tokens import (
    AccessClaims,
    InvalidAccessTokenError,
    Role,
    verify_access_token,
)
from evalcore.cancellation import cancel_key, is_cancel_requested, request_cancel
from evalcore.dataset_rows import (
    DatasetRow,
    DatasetRowInput,
    delete_dataset_rows,
    insert_dataset_rows,
    list_dataset_rows,
)
from evalcore.jobs import RUN_JOB_NAME, enqueue_run, redis_settings, run_job_id
from evalcore.mock_provider import MockProvider
from evalcore.mongo import DATASET_ROWS, RESULTS, RUNS, ensure_indexes
from evalcore.prompts import (
    VARIABLE_RE,
    MissingVariablesError,
    extract_variables,
    render_prompt,
    render_template,
)
from evalcore.providers import (
    GenerationRequest,
    GenerationResult,
    ProviderClient,
    ProviderError,
)
from evalcore.run_logging import (
    RunIdFilter,
    RunIdFormatter,
    configure_logging,
    run_id_var,
)
from evalcore.run_store import (
    cancel_queued_run,
    delete_run,
    get_run,
    insert_run,
    list_results,
    list_runs,
    upsert_result,
)
from evalcore.runs import (
    TERMINAL_STATUSES,
    ModelSnapshot,
    ModelSummary,
    PromptSnapshot,
    Result,
    Run,
    RunSnapshot,
    RunStatus,
    RunTotals,
    ScorerSnapshot,
    Usage,
    compute_cost,
    is_context_limited,
)
from evalcore.scorers import Score, normalize_text, score_rule

__all__ = [
    "DATASET_ROWS",
    "RESULTS",
    "RUNS",
    "RUN_JOB_NAME",
    "TERMINAL_STATUSES",
    "VARIABLE_RE",
    "AccessClaims",
    "DatasetRow",
    "DatasetRowInput",
    "GenerationRequest",
    "GenerationResult",
    "InvalidAccessTokenError",
    "MissingVariablesError",
    "MockProvider",
    "ModelSnapshot",
    "ModelSummary",
    "PromptSnapshot",
    "ProviderClient",
    "ProviderError",
    "Result",
    "Role",
    "Run",
    "RunIdFilter",
    "RunIdFormatter",
    "RunSnapshot",
    "RunStatus",
    "RunTotals",
    "Score",
    "ScorerSnapshot",
    "Usage",
    "cancel_key",
    "cancel_queued_run",
    "compute_cost",
    "configure_logging",
    "delete_dataset_rows",
    "delete_run",
    "enqueue_run",
    "ensure_indexes",
    "extract_variables",
    "get_run",
    "insert_dataset_rows",
    "insert_run",
    "is_cancel_requested",
    "is_context_limited",
    "list_dataset_rows",
    "list_results",
    "list_runs",
    "normalize_text",
    "redis_settings",
    "render_prompt",
    "render_template",
    "request_cancel",
    "run_id_var",
    "run_job_id",
    "score_rule",
    "upsert_result",
    "verify_access_token",
]
