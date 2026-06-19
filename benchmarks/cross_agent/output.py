"""Structured JSONL and CSV output writers."""

from __future__ import annotations

import csv
import json
import shutil
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
    "input_token_source",
    "output_token_source",
    "failure_count",
    "recall_context_chars",
    "recall_hit_count",
    "agent_managed",
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
                    "input_token_source": record.input_token_source,
                    "output_token_source": record.output_token_source,
                    "failure_count": record.failure_count,
                    "recall_context_chars": record.recall_context_chars,
                    "recall_hit_count": record.recall_hit_count,
                    "agent_managed": record.agent_managed,
                }
            )


def default_output_paths(output_dir: Path, run_id: str) -> dict[str, Path]:
    run_dir = output_dir / run_id
    return {
        "run_dir": run_dir,
        "queries_jsonl": run_dir / "queries.jsonl",
        "queries_csv": run_dir / "queries.csv",
        "summary_json": run_dir / "summary.json",
    }


def prepare_run_directory(paths: dict[str, Path], *, resume: bool) -> None:
    """Create or reset the run directory before artifact writes."""
    run_dir = paths["run_dir"]
    if resume:
        run_dir.mkdir(parents=True, exist_ok=True)
        return
    if run_dir.exists():
        shutil.rmtree(run_dir)
    run_dir.mkdir(parents=True, exist_ok=True)
    for artifact in ("queries_jsonl", "queries_csv", "summary_json"):
        path = paths[artifact]
        if path.exists():
            path.unlink()


def write_queries_jsonl(path: Path, records: list[QueryRecord], *, run_id: str) -> None:
    """Write the full query log atomically (truncate + rewrite)."""
    rows = [{"run_id": run_id, **record.to_dict()} for record in records]
    path.write_text(
        "".join(json.dumps(row, default=str) + "\n" for row in rows),
        encoding="utf-8",
    )
