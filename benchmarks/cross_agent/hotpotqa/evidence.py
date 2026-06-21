"""Persist raw HotpotQA retrieval evidence per run."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ..fixtures.hotpotqa import load_hotpotqa_config, load_hotpotqa_subset
from ..metrics import retrieval_hit_rate
from ..types import BenchmarkRunResult, QueryRecord


def _supporting_fact_recall(
    retrieved_ids: tuple[str, ...],
    supporting_facts: tuple[str, ...],
) -> float | None:
  return retrieval_hit_rate(retrieved_ids, supporting_facts)


def build_retrieval_evidence_rows(
  result: BenchmarkRunResult,
  *,
  supporting_facts_by_query: dict[str, tuple[str, ...]],
) -> list[dict[str, Any]]:
  rows: list[dict[str, Any]] = []
  for record in result.queries:
    supporting_facts = supporting_facts_by_query.get(record.query_id, ())
    rows.append(
      {
        "run_id": result.run_id,
        "query_id": record.query_id,
        "question": record.question,
        "expected_answer": record.expected_answer,
        "prediction": record.prediction,
        "expected_memory_ids": list(record.expected_memory_ids),
        "supporting_facts": list(supporting_facts),
        "retrieved_ids": list(record.retrieved_ids),
        "retrieval_hit_rate": record.retrieval_hit_rate,
        "supporting_fact_recall": _supporting_fact_recall(
          record.retrieved_ids,
          supporting_facts,
        ),
        "recall_context_chars": record.recall_context_chars,
        "recall_hit_count": record.recall_hit_count,
        "recall_time_ms": record.recall_time_ms,
        "agent_managed": record.agent_managed,
        "failure_reason": record.failure_reason,
        "failure_category": record.failure_category,
        "agent_failure_reason": record.agent_failure_reason,
        "agent_exit_code": record.agent_exit_code,
        "agent_timed_out": record.agent_timed_out,
      }
    )
  return rows


def write_retrieval_evidence(
  run_dir: Path,
  result: BenchmarkRunResult,
  *,
  supporting_facts_by_query: dict[str, tuple[str, ...]],
) -> Path:
  path = run_dir / "retrieval_evidence.jsonl"
  rows = build_retrieval_evidence_rows(
    result,
    supporting_facts_by_query=supporting_facts_by_query,
  )
  path.write_text(
    "".join(json.dumps(row, default=str) + "\n" for row in rows),
    encoding="utf-8",
  )
  return path


def supporting_facts_index() -> dict[str, tuple[str, ...]]:
  subset = load_hotpotqa_subset()
  return {
    str(query["query_id"]): tuple(str(mid) for mid in query.get("supporting_facts", ()))
    for query in subset["queries"]
  }


def answer_prompt_template() -> str:
  return str(load_hotpotqa_config()["answer_prompt_template"])
