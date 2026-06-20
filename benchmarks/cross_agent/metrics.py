"""Metric helpers and aggregation for cross-agent benchmarks."""

from __future__ import annotations

import re
import string
from typing import Any

from .types import AggregateMetrics, BenchmarkQuery, QueryRecord


def approximate_token_count(text: str) -> int:
    """Offline token estimate: whitespace-delimited words (documented approximation)."""
    if not text:
        return 0
    return len(re.findall(r"\S+", text))


def normalize_answer(text: str) -> str:
    return " ".join(text.lower().strip().split())


def exact_match_accuracy(expected: str | None, prediction: str | None) -> float | None:
    if expected is None or prediction is None:
        return None
    return 1.0 if normalize_answer(expected) == normalize_answer(prediction) else 0.0


def _normalize_hotpotqa_answer(text: str) -> str:
    lowered = text.lower()
    without_punctuation = "".join(char for char in lowered if char not in string.punctuation)
    without_articles = re.sub(r"\b(a|an|the)\b", " ", without_punctuation)
    return " ".join(without_articles.split())


def hotpotqa_exact_match_accuracy(
    expected: str | None,
    prediction: str | None,
) -> float | None:
    """HotpotQA exact match using the dataset's standard answer normalization."""
    if expected is None or prediction is None:
        return None
    expected_normalized = _normalize_hotpotqa_answer(expected)
    prediction_normalized = _normalize_hotpotqa_answer(prediction)
    return 1.0 if expected_normalized == prediction_normalized else 0.0


def retrieval_hit_rate(
    retrieved_ids: tuple[str, ...],
    expected_memory_ids: tuple[str, ...],
) -> float | None:
    if not expected_memory_ids:
        return None
    hits = sum(1 for mid in expected_memory_ids if mid in retrieved_ids)
    return hits / len(expected_memory_ids)


def percentile(values: list[float], pct: float) -> float | None:
    if not values:
        return None
    if len(values) == 1:
        return values[0]
    ordered = sorted(values)
    rank = (len(ordered) - 1) * (pct / 100.0)
    lower = int(rank)
    upper = min(lower + 1, len(ordered) - 1)
    weight = rank - lower
    return ordered[lower] * (1.0 - weight) + ordered[upper] * weight


def aggregate_query_records(records: list[QueryRecord]) -> AggregateMetrics:
    if not records:
        return AggregateMetrics(
            query_count=0,
            completed_query_count=0,
            mean_accuracy=None,
            task_success_rate=None,
            mean_retrieval_hit_rate=None,
            mean_query_time_ms=0.0,
            total_input_tokens=0,
            total_output_tokens=0,
            total_failure_count=0,
        )

    accuracies = [r.accuracy for r in records if r.accuracy is not None]
    successes = [r.task_success for r in records if r.task_success is not None]
    hit_rates = [
        r.retrieval_hit_rate for r in records if r.retrieval_hit_rate is not None
    ]
    completed = [r for r in records if r.failure_count == 0]

    return AggregateMetrics(
        query_count=len(records),
        completed_query_count=len(completed),
        mean_accuracy=(sum(accuracies) / len(accuracies)) if accuracies else None,
        task_success_rate=(sum(1 for s in successes if s) / len(successes))
        if successes
        else None,
        mean_retrieval_hit_rate=(sum(hit_rates) / len(hit_rates)) if hit_rates else None,
        mean_query_time_ms=sum(r.query_time_ms for r in records) / len(records),
        total_input_tokens=sum(r.input_tokens for r in records),
        total_output_tokens=sum(r.output_tokens for r in records),
        total_failure_count=sum(r.failure_count for r in records),
    )


def timing_aggregates(records: list[QueryRecord]) -> dict[str, float | int | None]:
    """Return mean/p95 query latency and token roll-ups."""
    if not records:
        return {
            "mean_query_time_ms": 0.0,
            "p95_query_time_ms": None,
            "mean_input_tokens": None,
            "total_input_tokens": 0,
            "total_output_tokens": 0,
            "total_failure_count": 0,
        }
    query_times = [r.query_time_ms for r in records]
    return {
        "mean_query_time_ms": sum(query_times) / len(query_times),
        "p95_query_time_ms": percentile(query_times, 95.0),
        "mean_input_tokens": sum(r.input_tokens for r in records) / len(records),
        "total_input_tokens": sum(r.input_tokens for r in records),
        "total_output_tokens": sum(r.output_tokens for r in records),
        "total_failure_count": sum(r.failure_count for r in records),
    }


def token_source_aggregates(records: list[QueryRecord]) -> dict[str, int]:
    """Count per-query token provenance labels across a run."""
    counts: dict[str, int] = {}
    for record in records:
        for label in (record.input_token_source, record.output_token_source):
            counts[label] = counts.get(label, 0) + 1
    return counts


def aggregate_by_category(
    records: list[QueryRecord],
    fixture_queries: tuple[BenchmarkQuery, ...],
) -> dict[str, dict[str, Any]]:
    """Roll up metrics keyed by LoCoMo category name."""
    category_by_query_id = {
        query.query_id: query.metadata.get("category_name", "unknown")
        for query in fixture_queries
    }
    buckets: dict[str, list[QueryRecord]] = {}
    for record in records:
        category = str(category_by_query_id.get(record.query_id, "unknown"))
        buckets.setdefault(category, []).append(record)

    summary: dict[str, dict[str, Any]] = {}
    for category, bucket in sorted(buckets.items()):
        aggregates = aggregate_query_records(bucket)
        timing = timing_aggregates(bucket)
        summary[category] = {
            "query_count": aggregates.query_count,
            "mean_accuracy": aggregates.mean_accuracy,
            "mean_retrieval_hit_rate": aggregates.mean_retrieval_hit_rate,
            "mean_query_time_ms": timing["mean_query_time_ms"],
            "p95_query_time_ms": timing["p95_query_time_ms"],
            "mean_input_tokens": timing["mean_input_tokens"],
            "total_input_tokens": timing["total_input_tokens"],
            "total_failure_count": timing["total_failure_count"],
        }
    return summary
