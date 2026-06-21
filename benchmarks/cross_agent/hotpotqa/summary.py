"""Aggregate HotpotQA matrix run summaries."""

from __future__ import annotations

import json
import statistics
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from ..fixtures.hotpotqa import (
    HOTPOTQA_SUBSET_VERSION,
    compute_subset_hash,
    load_hotpotqa_config,
)
from ..types import BenchmarkRunResult
from .cells import CellStatus, HotpotqaMatrixCell, iter_hotpotqa_matrix_cells
from .manifest import ResolvedExecutable, _portable_path


@dataclass
class HotpotqaCellSummary:
    agent: str
    backend: str
    top_k: int
    status: str
    rationale: str
    execution_mode: str | None
    use_mock_agent: bool | None
    runner_implementation: str | None
    agent_executable: str | None
    executable_source: str | None
    cli_mode: str | None
    run_id: str | None
    query_count: int
    mean_accuracy: float | None
    mean_retrieval_hit_rate: float | None
    mean_supporting_fact_recall: float | None
    mean_query_time_ms: float | None
    p95_query_time_ms: float | None
    total_input_tokens: int | None
    total_output_tokens: int | None
    total_failure_count: int | None
    index_storage_bytes: int | None
    completed_query_count: int | None = None
    input_token_sources: list[str] | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _percentile(values: list[float], pct: float) -> float | None:
    if not values:
        return None
    if len(values) == 1:
        return values[0]
    return statistics.quantiles(values, n=100)[int(pct) - 1]


def _storage_bytes(storage_dir: str | None) -> int | None:
    if not storage_dir:
        return None
    root = Path(storage_dir)
    if not root.exists():
        return None
    return sum(path.stat().st_size for path in root.rglob("*") if path.is_file())


def _mean_supporting_fact_recall(run_dir: Path) -> float | None:
    evidence_path = run_dir / "retrieval_evidence.jsonl"
    if not evidence_path.is_file():
        return None
    recalls: list[float] = []
    for line in evidence_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        value = row.get("supporting_fact_recall")
        if value is not None:
            recalls.append(float(value))
    if not recalls:
        return None
    return sum(recalls) / len(recalls)


def summarize_cell(
    cell: HotpotqaMatrixCell,
    *,
    result: BenchmarkRunResult | None,
    run_dir: Path | None,
    execution_mode: str | None = None,
    agent_executable: ResolvedExecutable | None = None,
    pending_rationale: str | None = None,
) -> HotpotqaCellSummary:
  common = {
      "agent": cell.agent.value,
      "backend": cell.backend.value,
      "top_k": cell.top_k,
      "status": CellStatus.PENDING.value if pending_rationale else cell.status.value,
      "rationale": pending_rationale or cell.rationale,
      "execution_mode": execution_mode,
      "agent_executable": (
          _portable_path(agent_executable.path) if agent_executable else None
      ),
      "executable_source": agent_executable.source if agent_executable else None,
  }
  if result is None:
      return HotpotqaCellSummary(
          **common,
          use_mock_agent=None,
          runner_implementation=None,
          cli_mode=None,
          run_id=None,
          query_count=0,
          mean_accuracy=None,
          mean_retrieval_hit_rate=None,
          mean_supporting_fact_recall=None,
          mean_query_time_ms=None,
          p95_query_time_ms=None,
          total_input_tokens=None,
          total_output_tokens=None,
          total_failure_count=None,
          completed_query_count=None,
          index_storage_bytes=None,
      )

  runner_implementation = (
      "mock-synthetic"
      if result.config.use_mock_agent
      else str(result.agent_metadata.get("runner_kind") or "cli")
  )
  cli_mode = result.agent_metadata.get("cli_mode")
  if cli_mode is None and agent_executable is not None:
      cli_mode = agent_executable.cli_mode

  query_times = [record.query_time_ms for record in result.queries]
  token_sources = sorted({record.input_token_source for record in result.queries})
  return HotpotqaCellSummary(
      **common,
      use_mock_agent=result.config.use_mock_agent,
      runner_implementation=runner_implementation,
      cli_mode=str(cli_mode) if cli_mode is not None else None,
      run_id=result.run_id,
      query_count=result.aggregates.query_count,
      mean_accuracy=result.aggregates.mean_accuracy,
      mean_retrieval_hit_rate=result.aggregates.mean_retrieval_hit_rate,
      mean_supporting_fact_recall=_mean_supporting_fact_recall(run_dir) if run_dir else None,
      mean_query_time_ms=result.aggregates.mean_query_time_ms,
      p95_query_time_ms=_percentile(query_times, 95),
      total_input_tokens=result.aggregates.total_input_tokens,
      total_output_tokens=result.aggregates.total_output_tokens,
      total_failure_count=result.aggregates.total_failure_count,
      completed_query_count=result.aggregates.completed_query_count,
      index_storage_bytes=_storage_bytes(result.storage_dir),
      input_token_sources=token_sources or None,
  )


def _cell_completed_successfully(row: HotpotqaCellSummary) -> bool:
    """True when every query in the cell completed without failures."""
    if row.query_count == 0:
        return False
    if row.completed_query_count is None:
        return False
    return row.completed_query_count == row.query_count


def build_matrix_summary(
    *,
    cell_summaries: list[HotpotqaCellSummary],
    output_root: Path,
    execution_mode: str = "comparison",
    use_mock_agent: bool = False,
    command: str | None = None,
    agent_executables: dict[str, ResolvedExecutable] | None = None,
) -> dict[str, Any]:
    config = load_hotpotqa_config()
    comparison_rows = [
        row
        for row in cell_summaries
        if row.run_id is not None
        and row.use_mock_agent is False
        and row.executable_source != "fake_double"
    ]
    attempted = comparison_rows
    completed = [row for row in comparison_rows if _cell_completed_successfully(row)]
    failed = [
        row
        for row in comparison_rows
        if row.query_count > 0
        and not _cell_completed_successfully(row)
        and (row.total_failure_count or 0) > 0
    ]
    test_double = [
        row
        for row in cell_summaries
        if row.run_id is not None
        and row.use_mock_agent is False
        and row.executable_source == "fake_double"
    ]
    mock_smoke = [
        row
        for row in cell_summaries
        if row.run_id is not None and row.use_mock_agent is True
    ]
    pending = [row for row in cell_summaries if row.status == CellStatus.PENDING.value]
    unsupported = [row for row in cell_summaries if row.status == CellStatus.UNSUPPORTED.value]

    tradeoffs: list[str] = []
    if not use_mock_agent and completed:
        hm_arch_rows = [row for row in completed if row.backend == "hm_arch"]
        no_memory_rows = [row for row in completed if row.backend == "no_memory"]
        if hm_arch_rows and no_memory_rows:
            hm_acc = [row.mean_accuracy for row in hm_arch_rows if row.mean_accuracy is not None]
            nm_acc = [row.mean_accuracy for row in no_memory_rows if row.mean_accuracy is not None]
            if hm_acc and nm_acc and statistics.mean(hm_acc) != statistics.mean(nm_acc):
                tradeoffs.append(
                    "Answer accuracy comparison "
                    f"(HM-Arch mean {statistics.mean(hm_acc):.2f}; "
                    f"no-memory mean {statistics.mean(nm_acc):.2f})."
                )
            k5_recall = next(
                (
                    row.mean_retrieval_hit_rate
                    for row in hm_arch_rows
                    if row.top_k == 5 and row.mean_retrieval_hit_rate is not None
                ),
                None,
            )
            k20_recall = next(
                (
                    row.mean_retrieval_hit_rate
                    for row in hm_arch_rows
                    if row.top_k == 20 and row.mean_retrieval_hit_rate is not None
                ),
                None,
            )
            if (
                k5_recall is not None
                and k20_recall is not None
                and k5_recall != k20_recall
            ):
                tradeoffs.append(
                    "HM-Arch retrieval hit rate by top-k "
                    f"(k=5: {k5_recall:.2f}, k=20: {k20_recall:.2f})."
                )
            hm_latency = [
                row.mean_query_time_ms for row in hm_arch_rows if row.mean_query_time_ms is not None
            ]
            nm_latency = [
                row.mean_query_time_ms
                for row in no_memory_rows
                if row.mean_query_time_ms is not None
            ]
            if hm_latency and nm_latency:
                tradeoffs.append(
                    "Mean query time comparison "
                    f"(HM-Arch {statistics.mean(hm_latency):.1f} ms; "
                    f"no-memory {statistics.mean(nm_latency):.1f} ms)."
                )
            hm_tokens = [
                row.total_input_tokens for row in hm_arch_rows if row.total_input_tokens is not None
            ]
            nm_tokens = [
                row.total_input_tokens
                for row in no_memory_rows
                if row.total_input_tokens is not None
            ]
            if hm_tokens and nm_tokens and statistics.mean(hm_tokens) != statistics.mean(nm_tokens):
                tradeoffs.append(
                    "Input token comparison "
                    f"(HM-Arch mean {statistics.mean(hm_tokens):.0f}; "
                    f"no-memory mean {statistics.mean(nm_tokens):.0f})."
                )
            token_sources = sorted(
                {
                    source
                    for row in completed
                    for source in (row.input_token_sources or [])
                }
            )
            if token_sources:
                tradeoffs.append(
                    "Input token counts are sourced from "
                    + ", ".join(token_sources)
                    + " CLI usage fields where available."
                )
    elif not use_mock_agent and attempted and not completed:
        tradeoffs.append(
            "No valid completed comparisons: all executed cells recorded agent or recall "
            "failures. See per-query failure_reason and agent_exit_code in queries.jsonl."
        )
    elif test_double:
        tradeoffs.append(
            "Test-double CLI cells completed for harness validation only; "
            "accuracy, latency, and token metrics are not agent conclusions."
        )
    elif pending and not attempted:
        tradeoffs.append(
            "No host agent CLIs were available for comparison; install codex, claude, "
            "or hermes and re-run scripts/run_hotpotqa_matrix.py --use-real-cli."
        )

    return {
        "benchmark": "hotpotqa",
        "issue": "MEM-77",
        "execution_mode": execution_mode,
        "use_mock_agent": use_mock_agent,
        "command": command,
        "subset_version": HOTPOTQA_SUBSET_VERSION,
        "subset_hash": compute_subset_hash(),
        "seed": int(config["seed"]),
        "answer_prompt_template": config["answer_prompt_template"],
        "top_k_values": [5, 20],
        "matrix_size": len(list(iter_hotpotqa_matrix_cells())),
        "executed_cells": len(attempted),
        "completed_cells": len(completed),
        "failed_cells": len(failed),
        "test_double_cells": len(test_double),
        "mock_smoke_cells": len(mock_smoke),
        "pending_cells": len(pending),
        "unsupported_cells": len(unsupported),
        "output_root": str(output_root),
        "agent_executables": (
            {
                agent: {**asdict(resolved), "path": _portable_path(resolved.path)}
                for agent, resolved in (agent_executables or {}).items()
                if resolved is not None
            }
            if agent_executables
            else None
        ),
        "agent_cli_unavailable": (
            [agent for agent, resolved in agent_executables.items() if resolved is None]
            if agent_executables
            else None
        ),
        "tradeoffs": tradeoffs,
        "cells": [row.to_dict() for row in cell_summaries],
    }


def write_matrix_summary(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
