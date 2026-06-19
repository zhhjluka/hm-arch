"""Raw trajectory writers for tau2-bench comparison runs."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ..types import BenchmarkRunResult, QueryRecord
from .config import Tau2Domain
from .fixtures import get_tau2_domain_fixture


def trajectory_record(
    *,
    domain: Tau2Domain,
    result: BenchmarkRunResult,
    record: QueryRecord,
    task_success_criteria: str | None = None,
) -> dict[str, Any]:
    """Build one raw trajectory row for a completed query."""
    return {
        "run_id": result.run_id,
        "domain": domain.value,
        "agent": result.config.agent.value,
        "backend": result.config.backend.value,
        "seed": result.config.seed,
        "query_id": record.query_id,
        "question": record.question,
        "expected_answer": record.expected_answer,
        "prediction": record.prediction,
        "accuracy": record.accuracy,
        "task_success": record.task_success,
        "task_success_criteria": task_success_criteria,
        "retrieval_hit_rate": record.retrieval_hit_rate,
        "recall_time_ms": record.recall_time_ms,
        "agent_time_ms": record.agent_time_ms,
        "query_time_ms": record.query_time_ms,
        "input_tokens": record.input_tokens,
        "output_tokens": record.output_tokens,
        "input_token_source": record.input_token_source,
        "output_token_source": record.output_token_source,
        "failure_count": record.failure_count,
        "retrieved_ids": list(record.retrieved_ids),
        "expected_memory_ids": list(record.expected_memory_ids),
        "recall_context_chars": record.recall_context_chars,
        "recall_hit_count": record.recall_hit_count,
        "agent_managed": record.agent_managed,
        "agent_metadata": result.agent_metadata,
    }


def write_run_trajectory(
    path: Path,
    *,
    domain: Tau2Domain,
    result: BenchmarkRunResult,
) -> None:
    """Write raw trajectories for one completed harness run."""
    criteria_by_id = {
        query.query_id: query.task_success_criteria
        for query in get_tau2_domain_fixture(domain).queries
    }
    rows = [
        trajectory_record(
            domain=domain,
            result=result,
            record=record,
            task_success_criteria=criteria_by_id.get(record.query_id),
        )
        for record in result.queries
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(json.dumps(row, default=str) + "\n" for row in rows),
        encoding="utf-8",
    )


def append_trajectory_index(path: Path, entries: list[dict[str, Any]]) -> None:
    """Append trajectory index rows to the comparison-level index file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        for entry in entries:
            handle.write(json.dumps(entry, default=str) + "\n")
