"""Structured JSONL and CSV output writers."""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any

from .types import BenchmarkRunResult, QueryRecord


_QUERY_CSV_FIELDS = [
    "run_id",
    "family",
    "query_id",
    "question",
    "expected_answer",
    "prediction",
    "accuracy",
    "task_success",
    "retrieval_hit_rate",
    "recall_time_ms",
    "agent_time_ms",
    "query_time_ms",
    "input_tokens",
    "output_tokens",
    "failure_count",
]


def append_query_jsonl(path: Path, record: QueryRecord, *, run_id: str) -> None:
    row = {"run_id": run_id, **record.to_dict()}
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(row, default=str) + "\n")


def write_summary_json(path: Path, result: BenchmarkRunResult) -> None:
    path.write_text(
        json.dumps(result.to_dict(), indent=2, default=str),
        encoding="utf-8",
    )


def write_queries_csv(path: Path, result: BenchmarkRunResult) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=_QUERY_CSV_FIELDS)
        writer.writeheader()
        for record in result.queries:
            writer.writerow(
                {
                    "run_id": result.run_id,
                    "family": record.family,
                    "query_id": record.query_id,
                    "question": record.question,
                    "expected_answer": record.expected_answer,
                    "prediction": record.prediction,
                    "accuracy": record.accuracy,
                    "task_success": record.task_success,
                    "retrieval_hit_rate": record.retrieval_hit_rate,
                    "recall_time_ms": record.recall_time_ms,
                    "agent_time_ms": record.agent_time_ms,
                    "query_time_ms": record.query_time_ms,
                    "input_tokens": record.input_tokens,
                    "output_tokens": record.output_tokens,
                    "failure_count": record.failure_count,
                }
            )


def default_output_paths(output_dir: Path, run_id: str) -> dict[str, Path]:
    run_dir = output_dir / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    return {
        "run_dir": run_dir,
        "queries_jsonl": run_dir / "queries.jsonl",
        "queries_csv": run_dir / "queries.csv",
        "summary_json": run_dir / "summary.json",
    }
