"""Metric helpers and aggregation for cross-agent benchmarks."""

from __future__ import annotations

import re
import string

from .types import AggregateMetrics, QueryRecord


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
