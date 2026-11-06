"""Run document shapes, cost, and context-limit helpers."""

from datetime import UTC, datetime

from evalcore.runs import (
    ModelSnapshot,
    ModelSummary,
    PromptSnapshot,
    Run,
    RunSnapshot,
    RunStatus,
    RunTotals,
    Usage,
    compute_cost,
    is_context_limited,
)


def make_model(**overrides: object) -> ModelSnapshot:
    fields: dict[str, object] = {
        "model_config_id": 2,
        "provider_id": 5,
        "provider_name": "prov",
        "provider_kind": "mock",
        "model_name": "mock-1",
        "temperature": 0.0,
        "max_tokens": 256,
        "context_length": 4096,
        "input_price_per_1k": 0.1,
        "output_price_per_1k": 0.2,
        "max_concurrency": 1,
        "requests_per_minute": None,
        "base_url": "",
        "api_key_env": "",
        "digest": None,
    }
    fields.update(overrides)
    return ModelSnapshot(**fields)  # type: ignore[arg-type]


def test_compute_cost() -> None:
    usage = Usage(input_tokens=1000, output_tokens=500)
    assert compute_cost(usage, make_model()) == 0.1 + 0.1


def test_compute_cost_zero_prices() -> None:
    usage = Usage(input_tokens=10, output_tokens=10)
    assert compute_cost(usage, make_model(input_price_per_1k=0.0, output_price_per_1k=0.0)) == 0.0


def test_is_context_limited_boundary() -> None:
    model = make_model(context_length=100)
    assert is_context_limited(Usage(input_tokens=60, output_tokens=40), model) is True
    assert is_context_limited(Usage(input_tokens=60, output_tokens=39), model) is False


def test_run_round_trips_through_dump_and_validate() -> None:
    run = Run(
        id="66f0a0b1c2d3e4f506172839",
        organization_id=1,
        project_id=2,
        prompt_version_id=3,
        dataset_id=4,
        model_config_ids=[2],
        scorer_ids=[1],
        snapshot=RunSnapshot(
            prompt=PromptSnapshot(
                prompt_version_id=3,
                template_id=6,
                number=1,
                system_message="sys",
                body="hi {{q}}",
                variables=["q"],
            ),
            models=[make_model()],
            scorers=[],
            seed=42,
        ),
        status=RunStatus.RUNNING,
        created_by=9,
        created_at=datetime(2026, 10, 31, 12, 0, 0, tzinfo=UTC),
        finished_at=None,
        totals=RunTotals(rows=10, done=4, failed=1),
        summary={
            "2": ModelSummary(
                mean_score=0.5,
                by_scorer={"1": 0.5},
                p95_latency_ms=100,
                cost_usd=0.01,
                error_count=1,
            )
        },
        error=None,
    )
    assert Run.model_validate(run.model_dump()) == run
    assert run.model_dump()["status"] == "running"
