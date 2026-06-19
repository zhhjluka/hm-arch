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


@dataclass
class HotpotqaCellSummary:
    agent: str
    backend: str
    top_k: int
    status: str
    rationale: str
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
) -> HotpotqaCellSummary:
    if result is None:
        return HotpotqaCellSummary(
            agent=cell.agent.value,
            backend=cell.backend.value,
            top_k=cell.top_k,
            status=cell.status.value,
            rationale=cell.rationale,
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
            index_storage_bytes=None,
        )

    query_times = [record.query_time_ms for record in result.queries]
    return HotpotqaCellSummary(
        agent=cell.agent.value,
        backend=cell.backend.value,
        top_k=cell.top_k,
        status=cell.status.value,
        rationale=cell.rationale,
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
        index_storage_bytes=_storage_bytes(result.storage_dir),
    )


def build_matrix_summary(
    *,
    cell_summaries: list[HotpotqaCellSummary],
    output_root: Path,
) -> dict[str, Any]:
    config = load_hotpotqa_config()
    executed = [row for row in cell_summaries if row.run_id is not None]
    pending = [row for row in cell_summaries if row.status == CellStatus.PENDING.value]
    unsupported = [row for row in cell_summaries if row.status == CellStatus.UNSUPPORTED.value]

    tradeoffs: list[str] = []
    hm_arch_rows = [row for row in executed if row.backend == "hm_arch"]
    no_memory_rows = [row for row in executed if row.backend == "no_memory"]
    if hm_arch_rows and no_memory_rows:
        hm_acc = [row.mean_accuracy for row in hm_arch_rows if row.mean_accuracy is not None]
        nm_acc = [row.mean_accuracy for row in no_memory_rows if row.mean_accuracy is not None]
        if hm_acc and nm_acc:
            tradeoffs.append(
                "HM-Arch improves answer accuracy over no-memory by supplying recalled context "
                f"(mean accuracy {statistics.mean(hm_acc):.2f} vs {statistics.mean(nm_acc):.2f})."
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
        if k5_recall is not None and k20_recall is not None:
            tradeoffs.append(
                "HM-Arch retrieval hit rate scales with top-k "
                f"(k=5: {k5_recall:.2f}, k=20: {k20_recall:.2f})."
            )
        hm_latency = [
            row.mean_query_time_ms for row in hm_arch_rows if row.mean_query_time_ms is not None
        ]
        nm_latency = [
            row.mean_query_time_ms for row in no_memory_rows if row.mean_query_time_ms is not None
        ]
        if hm_latency and nm_latency:
            tradeoffs.append(
                "Recall adds latency versus no-memory "
                f"(mean query time {statistics.mean(hm_latency):.1f} ms vs "
                f"{statistics.mean(nm_latency):.1f} ms)."
            )
        hm_tokens = [
            row.total_input_tokens for row in hm_arch_rows if row.total_input_tokens is not None
        ]
        nm_tokens = [
            row.total_input_tokens for row in no_memory_rows if row.total_input_tokens is not None
        ]
        if hm_tokens and nm_tokens:
            tradeoffs.append(
                "Higher top-k and recalled context increase input tokens "
                f"(HM-Arch mean {statistics.mean(hm_tokens):.0f} vs "
                f"no-memory {statistics.mean(nm_tokens):.0f})."
            )

    return {
        "benchmark": "hotpotqa",
        "issue": "MEM-77",
        "subset_version": HOTPOTQA_SUBSET_VERSION,
        "subset_hash": compute_subset_hash(),
        "seed": int(config["seed"]),
        "answer_prompt_template": config["answer_prompt_template"],
        "top_k_values": [5, 20],
        "matrix_size": len(list(iter_hotpotqa_matrix_cells())),
        "executed_cells": len(executed),
        "pending_cells": len(pending),
        "unsupported_cells": len(unsupported),
        "output_root": str(output_root),
        "tradeoffs": tradeoffs,
        "cells": [row.to_dict() for row in cell_summaries],
    }


def write_matrix_summary(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
