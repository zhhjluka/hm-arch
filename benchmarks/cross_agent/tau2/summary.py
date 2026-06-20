"""Final tau2-bench comparison summary table generation."""

from __future__ import annotations

import csv
import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from .config import OPENCLAW_PENDING_ISSUE, Tau2ComparisonConfig, Tau2ComparisonMode, Tau2Domain
from .types import Tau2CellResult


@dataclass
class Tau2SummaryRow:
    """One row in the final agent × memory comparison table."""

    agent: str
    backend: str
    status: str
    retail_task_success_rate: float | None
    retail_mean_accuracy: float | None
    airline_task_success_rate: float | None
    airline_mean_accuracy: float | None
    mean_query_time_ms: float | None
    total_input_tokens: int
    total_output_tokens: int
    total_failure_count: int
    retail_run_id: str | None = None
    airline_run_id: str | None = None
    rationale: str | None = None
    retail_trajectory_path: str | None = None
    airline_trajectory_path: str | None = None
    excluded_from_benchmark_table: bool = False
    exclusion_reason: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class Tau2ComparisonReport:
    """Full comparison artifact bundle."""

    issue: str = "MEM-76"
    openclaw_pending_issue: str = OPENCLAW_PENDING_ISSUE
    mode: str = "real"
    provenance: dict[str, Any] = field(default_factory=dict)
    domains: list[str] = field(default_factory=lambda: [d.value for d in Tau2Domain])
    rows: list[Tau2SummaryRow] = field(default_factory=list)
    matrix_status: list[dict[str, Any]] = field(default_factory=list)
    benchmark_rows: list[Tau2SummaryRow] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "issue": self.issue,
            "openclaw_pending_issue": self.openclaw_pending_issue,
            "mode": self.mode,
            "provenance": self.provenance,
            "domains": self.domains,
            "rows": [row.to_dict() for row in self.rows],
            "benchmark_rows": [row.to_dict() for row in self.benchmark_rows],
            "matrix_status": self.matrix_status,
        }


def _row_is_benchmark_eligible(
    cell: Tau2CellResult,
    *,
    comparison: Tau2ComparisonConfig | None,
) -> tuple[bool, str | None]:
    if comparison is None:
        return True, None
    if comparison.mode in {Tau2ComparisonMode.SMOKE, Tau2ComparisonMode.HARNESS}:
        return False, f"mode={comparison.mode.value} is harness-only"
    if comparison.use_harness_agent:
        return False, "use_harness_agent is set"
    if cell.status != "completed":
        return False, f"cell status={cell.status}"
    return True, None


def build_summary_table(
    cell_results: list[Tau2CellResult],
    *,
    comparison: Tau2ComparisonConfig | None = None,
) -> Tau2ComparisonReport:
    """Aggregate per-domain runs into the final comparison table."""
    report = Tau2ComparisonReport()
    if comparison is not None:
        report.mode = comparison.mode.value
        report.provenance = comparison.provenance()

    for cell in sorted(cell_results, key=lambda item: (item.coordinate.agent.value, item.coordinate.backend.value)):
        report.matrix_status.append(cell.to_status_dict())

        retail = cell.domain_results.get(Tau2Domain.RETAIL)
        airline = cell.domain_results.get(Tau2Domain.AIRLINE)

        retail_agg = retail.result.aggregates if retail and retail.result else None
        airline_agg = airline.result.aggregates if airline and airline.result else None
        retail_metrics = retail.metrics if retail else None
        airline_metrics = airline.metrics if airline else None

        query_times: list[float] = []
        if retail_metrics and retail_metrics.mean_task_time_ms is not None:
            query_times.append(retail_metrics.mean_task_time_ms)
        elif retail_agg and retail_agg.query_count:
            query_times.append(retail_agg.mean_query_time_ms)
        if airline_metrics and airline_metrics.mean_task_time_ms is not None:
            query_times.append(airline_metrics.mean_task_time_ms)
        elif airline_agg and airline_agg.query_count:
            query_times.append(airline_agg.mean_query_time_ms)

        eligible, exclusion_reason = _row_is_benchmark_eligible(cell, comparison=comparison)
        row = Tau2SummaryRow(
            agent=cell.coordinate.agent.value,
            backend=cell.coordinate.backend.value,
            status=cell.status,
            retail_task_success_rate=(
                retail_metrics.task_success_rate
                if retail_metrics
                else (retail_agg.task_success_rate if retail_agg else None)
            ),
            retail_mean_accuracy=retail_agg.mean_accuracy if retail_agg else None,
            airline_task_success_rate=(
                airline_metrics.task_success_rate
                if airline_metrics
                else (airline_agg.task_success_rate if airline_agg else None)
            ),
            airline_mean_accuracy=airline_agg.mean_accuracy if airline_agg else None,
            mean_query_time_ms=(
                sum(query_times) / len(query_times) if query_times else None
            ),
            total_input_tokens=(
                (retail_metrics.total_input_tokens if retail_metrics else 0)
                + (airline_metrics.total_input_tokens if airline_metrics else 0)
                + (retail_agg.total_input_tokens if retail_agg else 0)
                + (airline_agg.total_input_tokens if airline_agg else 0)
            ),
            total_output_tokens=(
                (retail_metrics.total_output_tokens if retail_metrics else 0)
                + (airline_metrics.total_output_tokens if airline_metrics else 0)
                + (retail_agg.total_output_tokens if airline_agg else 0)
                + (airline_agg.total_output_tokens if airline_agg else 0)
            ),
            total_failure_count=(
                (retail_metrics.total_failure_count if retail_metrics else 0)
                + (airline_metrics.total_failure_count if airline_metrics else 0)
                + (retail_agg.total_failure_count if retail_agg else 0)
                + (airline_agg.total_failure_count if airline_agg else 0)
            ),
            retail_run_id=(
                retail.run_id
                if retail and retail.run_id
                else (retail.result.run_id if retail and retail.result else None)
            ),
            airline_run_id=(
                airline.run_id
                if airline and airline.run_id
                else (airline.result.run_id if airline and airline.result else None)
            ),
            rationale=cell.rationale,
            retail_trajectory_path=retail.trajectory_path if retail else None,
            airline_trajectory_path=airline.trajectory_path if airline else None,
            excluded_from_benchmark_table=not eligible,
            exclusion_reason=exclusion_reason,
        )
        report.rows.append(row)
        if eligible:
            report.benchmark_rows.append(row)

    return report


_SUMMARY_CSV_FIELDS = [
    "agent",
    "backend",
    "status",
    "retail_task_success_rate",
    "retail_mean_accuracy",
    "airline_task_success_rate",
    "airline_mean_accuracy",
    "mean_query_time_ms",
    "total_input_tokens",
    "total_output_tokens",
    "total_failure_count",
    "retail_run_id",
    "airline_run_id",
    "rationale",
    "retail_trajectory_path",
    "airline_trajectory_path",
    "excluded_from_benchmark_table",
    "exclusion_reason",
]


def write_comparison_artifacts(
    output_root: Path,
    report: Tau2ComparisonReport,
) -> dict[str, Path]:
    """Persist summary table and matrix status under *output_root*."""
    output_root.mkdir(parents=True, exist_ok=True)
    summary_json = output_root / "summary_table.json"
    summary_csv = output_root / "summary_table.csv"
    benchmark_json = output_root / "benchmark_table.json"
    benchmark_csv = output_root / "benchmark_table.csv"
    matrix_status = output_root / "matrix_status.json"
    openclaw_pending = output_root / "openclaw_pending.json"

    summary_json.write_text(
        json.dumps(report.to_dict(), indent=2, default=str),
        encoding="utf-8",
    )
    matrix_status.write_text(
        json.dumps(report.matrix_status, indent=2, default=str),
        encoding="utf-8",
    )
    benchmark_json.write_text(
        json.dumps(
            {
                "issue": report.issue,
                "mode": report.mode,
                "rows": [row.to_dict() for row in report.benchmark_rows],
            },
            indent=2,
            default=str,
        ),
        encoding="utf-8",
    )

    with summary_csv.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=_SUMMARY_CSV_FIELDS)
        writer.writeheader()
        for row in report.rows:
            writer.writerow(row.to_dict())

    with benchmark_csv.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=_SUMMARY_CSV_FIELDS)
        writer.writeheader()
        for row in report.benchmark_rows:
            writer.writerow(row.to_dict())

    openclaw_rows = [row.to_dict() for row in report.rows if row.agent == "openclaw"]
    openclaw_pending.write_text(
        json.dumps(
            {
                "issue": OPENCLAW_PENDING_ISSUE,
                "message": (
                    "OpenClaw tau2-bench cells are deferred until OpenClaw "
                    "integration is verified end-to-end."
                ),
                "cells": openclaw_rows,
            },
            indent=2,
            default=str,
        ),
        encoding="utf-8",
    )

    return {
        "summary_json": summary_json,
        "summary_csv": summary_csv,
        "benchmark_json": benchmark_json,
        "benchmark_csv": benchmark_csv,
        "matrix_status": matrix_status,
        "openclaw_pending": openclaw_pending,
    }
