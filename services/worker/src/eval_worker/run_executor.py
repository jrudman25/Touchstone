"""The execute_run job: render, generate, score, and persist results.

Runs are restartable: results upsert on the unique
(run_id, model_config_id, row_index) key, rows that already have a result
are skipped, and the final totals/summary are recomputed from results so
interrupted increments cannot corrupt the outcome. Cancellation is a Redis
flag checked per row; in-flight rows finish but no new rows start.
"""

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Any

from arq import ArqRedis
from pymongo.asynchronous.database import AsyncDatabase

from eval_worker.providers import build_provider
from eval_worker.rate_limit import RateLimiter
from eval_worker.settings import Settings
from evalcore import (
    TERMINAL_STATUSES,
    DatasetRow,
    GenerationRequest,
    MissingVariablesError,
    ModelSnapshot,
    ProviderClient,
    ProviderError,
    Run,
    RunStatus,
    RunTotals,
    Usage,
    compute_cost,
    existing_row_indexes,
    expire_events,
    finalize_run,
    get_run,
    inc_totals,
    is_cancel_requested,
    is_context_limited,
    list_dataset_rows,
    mark_running,
    publish_event,
    recompute_run_totals_and_summary,
    render_prompt,
    render_template,
    run_id_var,
    score_rule,
    upsert_result,
)
from evalcore.cancellation import cancel_key

logger = logging.getLogger("eval_worker.run_executor")

ProviderFactory = Callable[..., ProviderClient]
PAGE_SIZE = 200


async def execute_run(ctx: dict[str, Any], run_id: str) -> None:
    """arq job entrypoint; never raises (the run doc is the record)."""
    token = run_id_var.set(run_id)
    try:
        db: AsyncDatabase[dict[str, Any]] = ctx["db"]
        redis: ArqRedis = ctx["redis"]
        settings: Settings = ctx["settings"]
        factory: ProviderFactory = ctx.get("provider_factory", build_provider)
        try:
            await _execute(db, redis, settings, factory, run_id)
        except Exception as exc:
            logger.exception("run failed unexpectedly: %s", exc)
            await _fail(db, redis, settings, run_id, str(exc)[:500])
    finally:
        run_id_var.reset(token)


async def _fail(
    db: AsyncDatabase[dict[str, Any]],
    redis: ArqRedis,
    settings: Settings,
    run_id: str,
    message: str,
) -> None:
    try:
        run = await get_run(db, run_id)
        totals, summary = await _recompute(db, run_id, run)
        await finalize_run(
            db,
            run_id,
            status=RunStatus.FAILED,
            error=message,
            totals=totals,
            summary=summary,
            now=datetime.now(UTC),
        )
        await publish_event(
            redis,
            run_id,
            "status",
            {"status": "failed", "error": message},
            maxlen=settings.events_maxlen,
        )
        await expire_events(redis, run_id, settings.events_ttl_seconds)
    except Exception:
        logger.exception("could not persist the failed state")


async def _recompute(
    db: AsyncDatabase[dict[str, Any]], run_id: str, run: Run | None
) -> tuple[RunTotals, dict[str, Any]]:
    totals, summary = await recompute_run_totals_and_summary(db, run_id)
    rows = run.totals.rows if run is not None else 0
    return RunTotals(rows=rows, done=totals.done, failed=totals.failed), summary


async def _execute(
    db: AsyncDatabase[dict[str, Any]],
    redis: ArqRedis,
    settings: Settings,
    factory: ProviderFactory,
    run_id: str,
) -> None:
    run = await get_run(db, run_id)
    if run is None:
        logger.warning("run document not found")
        return
    if run.status in TERMINAL_STATUSES:
        logger.info("run already %s; nothing to do", run.status.value)
        return
    maxlen = settings.events_maxlen
    ttl = settings.events_ttl_seconds

    if await is_cancel_requested(redis, run_id):
        await _finalize(db, redis, run_id, run, RunStatus.CANCELLED, None, maxlen, ttl)
        return

    if await mark_running(db, run_id) is None:
        logger.warning("run left a runnable state before it could start")
        return
    await publish_event(
        redis, run_id, "status", {"status": "running", "error": None}, maxlen=maxlen
    )

    expected_rows = run.totals.rows // len(run.snapshot.models)
    done = run.totals.done
    failed = run.totals.failed
    cancelled = False

    for model in run.snapshot.models:
        if cancelled:
            break
        done, failed, cancelled = await _execute_model(
            db,
            redis,
            settings,
            factory,
            run,
            run_id,
            model,
            expected_rows,
            done,
            failed,
            maxlen,
        )

    status = RunStatus.CANCELLED if cancelled else RunStatus.FINISHED
    await _finalize(db, redis, run_id, run, status, None, maxlen, ttl)


async def _finalize(
    db: AsyncDatabase[dict[str, Any]],
    redis: ArqRedis,
    run_id: str,
    run: Run,
    status: RunStatus,
    error: str | None,
    maxlen: int,
    ttl: int,
) -> None:
    totals, summary = await _recompute(db, run_id, run)
    await finalize_run(
        db,
        run_id,
        status=status,
        error=error,
        totals=totals,
        summary=summary,
        now=datetime.now(UTC),
    )
    await publish_event(
        redis,
        run_id,
        "status",
        {"status": status.value, "error": error},
        maxlen=maxlen,
    )
    await publish_event(
        redis,
        run_id,
        "summary",
        {"totals": totals.model_dump(), "summary": {k: v.model_dump() for k, v in summary.items()}},
        maxlen=maxlen,
    )
    await expire_events(redis, run_id, ttl)
    await redis.delete(cancel_key(run_id))


async def _execute_model(
    db: AsyncDatabase[dict[str, Any]],
    redis: ArqRedis,
    settings: Settings,
    factory: ProviderFactory,
    run: Run,
    run_id: str,
    model: ModelSnapshot,
    expected_rows: int,
    done: int,
    failed: int,
    maxlen: int,
) -> tuple[int, int, bool]:
    """One model over the whole dataset; returns updated counters + cancel."""
    existing = await existing_row_indexes(db, run_id, model.model_config_id)
    semaphore = asyncio.Semaphore(model.max_concurrency)
    limiter = RateLimiter(model.requests_per_minute)
    seen = 0
    cancelled = False
    after: int | None = None

    while True:
        rows = await list_dataset_rows(db, run.dataset_id, after=after, limit=PAGE_SIZE)
        if not rows:
            break
        after = rows[-1].row_index
        seen += len(rows)

        answers: dict[str, str] = {}
        for row in rows:
            if row.expected is None or row.row_index in existing:
                continue
            try:
                answers[render_template(run.snapshot.prompt.body, row.input)] = row.expected
            except MissingVariablesError:
                continue
        try:
            provider = factory(model, seed=run.snapshot.seed, answers=answers)
            provider_error: str | None = None
        except ProviderError as exc:
            provider = None
            provider_error = str(exc)

        async def check_cancel() -> bool:
            return cancelled or await is_cancel_requested(redis, run_id)

        async def process(
            row: DatasetRow,
            row_provider: ProviderClient | None,
            row_provider_error: str | None,
        ) -> None:
            nonlocal done, failed, cancelled
            if row.row_index in existing or cancelled:
                return
            result = await _score_row(
                run,
                model,
                row,
                row_provider,
                row_provider_error,
                semaphore,
                limiter,
                check_cancel,
            )
            if result is None:
                cancelled = True
                return
            result["run_id"] = run_id
            inserted = await upsert_result(db, result)
            if inserted:
                await inc_totals(db, run_id, done=1, failed=1 if result["error"] else 0)
                done += 1
                if result["error"]:
                    failed += 1
                await publish_event(
                    redis,
                    run_id,
                    "result",
                    {
                        "result": _event_result(result, run_id),
                        "totals": {"done": done, "failed": failed},
                    },
                    maxlen=maxlen,
                )

        await asyncio.gather(*(process(row, provider, provider_error) for row in rows))
        if cancelled:
            break

    if seen < expected_rows:
        raise ValueError(f"Dataset has {seen} rows but the run expected {expected_rows}")
    return done, failed, cancelled


def _event_result(result: dict[str, Any], run_id: str) -> dict[str, Any]:
    data = dict(result)
    data["run_id"] = run_id
    return data


async def _score_row(
    run: Run,
    model: ModelSnapshot,
    row: DatasetRow,
    provider: ProviderClient | None,
    provider_error: str | None,
    semaphore: asyncio.Semaphore,
    limiter: RateLimiter,
    check_cancel: Callable[[], Awaitable[bool]],
) -> dict[str, Any] | None:
    base: dict[str, Any] = {
        "row_index": row.row_index,
        "model_config_id": model.model_config_id,
        "input": row.input,
        "expected": row.expected,
        "rendered_prompt": "",
        "output": None,
        "usage": None,
        "latency_ms": None,
        "cost_usd": None,
        "context_limited": False,
        "scores": [],
    }
    try:
        rendered_system, rendered_body = render_prompt(
            run.snapshot.prompt.system_message, run.snapshot.prompt.body, row.input
        )
    except MissingVariablesError as exc:
        return {**base, "error": str(exc)}
    base["rendered_prompt"] = rendered_body
    if provider_error is not None:
        return {**base, "error": provider_error}
    async with semaphore:
        if await check_cancel():
            return None
        await limiter.acquire()
        if provider is None:
            return {**base, "error": "Provider unavailable"}
        started = time.perf_counter()
        try:
            generated = await provider.generate(
                GenerationRequest(
                    model_name=model.model_name,
                    system_message=rendered_system,
                    prompt=rendered_body,
                    temperature=model.temperature,
                    max_tokens=model.max_tokens,
                )
            )
        except ProviderError as exc:
            return {**base, "error": str(exc)}
        latency_ms = int((time.perf_counter() - started) * 1000)
    usage = {"input_tokens": generated.input_tokens, "output_tokens": generated.output_tokens}
    scores = [
        score_rule(scorer.kind, scorer.scorer_id, generated.output, row.expected).model_dump()
        for scorer in run.snapshot.scorers
        if scorer.kind != "llm_judge"
    ]
    usage_model = Usage.model_validate(usage)
    return {
        **base,
        "output": generated.output,
        "usage": usage,
        "latency_ms": latency_ms,
        "cost_usd": compute_cost(usage_model, model),
        "context_limited": is_context_limited(usage_model, model),
        "error": None,
        "scores": scores,
    }
