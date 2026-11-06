"""Authoritative run totals and per-model summary from results.

Recomputed from the ``results`` collection at run end (and exposed for
rechecks), so missed or double increments from a crash cannot corrupt the
final numbers. ``totals.done`` counts every stored result including errored
ones; ``totals.failed`` is the errored subset; null scores never enter means.
"""

from typing import Any

from bson import ObjectId
from pymongo.asynchronous.database import AsyncDatabase

from evalcore.mongo import RESULTS
from evalcore.runs import ModelSummary, RunTotals


async def recompute_run_totals_and_summary(
    db: AsyncDatabase[dict[str, Any]], run_id: str
) -> tuple[RunTotals, dict[str, ModelSummary]]:
    """Aggregate results into totals plus a per-model summary."""
    run_oid = ObjectId(run_id)
    pipeline: list[dict[str, Any]] = [
        {"$match": {"run_id": run_oid}},
        {
            "$facet": {
                "per_model": [
                    {
                        "$group": {
                            "_id": "$model_config_id",
                            "done": {"$sum": 1},
                            "error_count": {"$sum": {"$cond": [{"$ne": ["$error", None]}, 1, 0]}},
                            "cost_usd": {"$sum": {"$ifNull": ["$cost_usd", 0]}},
                            "p95": {
                                "$percentile": {
                                    "input": {
                                        "$cond": [
                                            {"$eq": ["$error", None]},
                                            "$latency_ms",
                                            None,
                                        ]
                                    },
                                    "p": [0.95],
                                    "method": "approximate",
                                }
                            },
                        }
                    }
                ],
                "scorer_means": [
                    {"$unwind": "$scores"},
                    {"$match": {"scores.value": {"$ne": None}}},
                    {
                        "$group": {
                            "_id": {
                                "model": "$model_config_id",
                                "scorer": "$scores.scorer_id",
                            },
                            "mean": {"$avg": "$scores.value"},
                        }
                    },
                ],
                "model_means": [
                    {"$unwind": "$scores"},
                    {"$match": {"scores.value": {"$ne": None}}},
                    {
                        "$group": {
                            "_id": "$model_config_id",
                            "mean": {"$avg": "$scores.value"},
                        }
                    },
                ],
            }
        },
    ]
    cursor = await db[RESULTS].aggregate(pipeline)
    docs = [doc async for doc in cursor]
    facet = docs[0] if docs else {"per_model": [], "scorer_means": [], "model_means": []}
    scorer_means = {
        (entry["_id"]["model"], str(entry["_id"]["scorer"])): entry["mean"]
        for entry in facet["scorer_means"]
    }
    model_means = {entry["_id"]: entry["mean"] for entry in facet["model_means"]}
    summary: dict[str, ModelSummary] = {}
    done_total = 0
    failed_total = 0
    for group in facet["per_model"]:
        model_id = group["_id"]
        p95_values = group["p95"] or []
        p95 = p95_values[0] if p95_values and p95_values[0] is not None else None
        done_total += group["done"]
        failed_total += group["error_count"]
        summary[str(model_id)] = ModelSummary(
            mean_score=model_means.get(model_id),
            by_scorer={
                scorer_id: mean
                for (mid, scorer_id), mean in scorer_means.items()
                if mid == model_id
            },
            p95_latency_ms=round(p95) if p95 is not None else None,
            cost_usd=group["cost_usd"],
            error_count=group["error_count"],
        )
    return RunTotals(done=done_total, failed=failed_total), summary
