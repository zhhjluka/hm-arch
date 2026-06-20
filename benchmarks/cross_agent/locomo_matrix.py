"""LoCoMo cross-agent memory comparison matrix (MEM-78 / HM-75)."""

from __future__ import annotations

import shlex
import sys
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any

from .agents.registry import is_supported_coordinate
from .compatibility import (
    CellImplementation,
    UnsupportedCombinationError,
    assert_supported,
    compatibility_cell,
    lookup_matrix_cell,
    matrix_key,
)
from .fixtures.locomo.loader import get_dataset_manifest
from .metrics import token_source_aggregates
from .runner import CrossAgentBenchmarkHarness
from .types import AgentKind, BenchmarkFamily, BenchmarkRunConfig, BenchmarkRunResult, MemoryBackendKind


class MatrixRunnerMode(str, Enum):
    """Whether the matrix executes offline mocks or production CLI runners."""

    MOCK = "mock"
    REAL = "real"


def _external_backend_available(backend: MemoryBackendKind) -> tuple[bool, str | None]:
    if backend is MemoryBackendKind.MEM0:
        try:
            import mem0  # type: ignore import-not-found  # noqa: F401
        except ImportError:
            return (
                False,
                "Mem0 backend requires the mem0ai package. Install with: pip install mem0ai",
            )
    if backend is MemoryBackendKind.OPENVIKING:
        try:
            import openviking  # type: ignore import-not-found  # noqa: F401
        except ImportError:
            return (
                False,
                "OpenViking backend requires the openviking package. "
                "Install with: pip install openviking",
            )
    return True, None


LOCOMO_BACKENDS: tuple[MemoryBackendKind, ...] = (
    MemoryBackendKind.NO_MEMORY,
    MemoryBackendKind.NATIVE_MEMORY,
    MemoryBackendKind.MEM0,
    MemoryBackendKind.OPENVIKING,
    MemoryBackendKind.HM_ARCH,
)

LOCOMO_AGENTS: tuple[AgentKind, ...] = (
    AgentKind.OPENCLAW,
    AgentKind.HERMES,
    AgentKind.CLAUDE_CODE,
    AgentKind.CODEX,
)


@dataclass(frozen=True)
class MatrixCellPlan:
    """One agent × backend coordinate in the LoCoMo comparison matrix."""

    agent: AgentKind
    backend: MemoryBackendKind
    status: str
    rationale: str
    run: bool
    runner_mode: MatrixRunnerMode | None = None


def locomo_matrix_plans(
    *,
    include_openclaw: bool = False,
    runner_mode: MatrixRunnerMode = MatrixRunnerMode.MOCK,
) -> list[MatrixCellPlan]:
    """Return the full LoCoMo matrix with explicit unsupported/pending notes."""
    use_mock_agent = runner_mode is MatrixRunnerMode.MOCK
    plans: list[MatrixCellPlan] = []
    for agent in LOCOMO_AGENTS:
        for backend in LOCOMO_BACKENDS:
            backend_cell = compatibility_cell(backend, agent)
            runner_cell = lookup_matrix_cell(agent, backend)

            if agent is AgentKind.OPENCLAW and not include_openclaw:
                plans.append(
                    MatrixCellPlan(
                        agent=agent,
                        backend=backend,
                        status="pending",
                        rationale=(
                            "OpenClaw cells deferred pending MEM-75 end-to-end "
                            "integration verification."
                        ),
                        run=False,
                    )
                )
                continue

            if not backend_cell.supported:
                plans.append(
                    MatrixCellPlan(
                        agent=agent,
                        backend=backend,
                        status="unsupported",
                        rationale=backend_cell.reason or "unsupported backend pairing",
                        run=False,
                    )
                )
                continue

            package_ok, package_reason = _external_backend_available(backend)
            if not package_ok:
                plans.append(
                    MatrixCellPlan(
                        agent=agent,
                        backend=backend,
                        status="unsupported",
                        rationale=package_reason or "required provider package missing",
                        run=False,
                    )
                )
                continue

            if (
                runner_mode is MatrixRunnerMode.REAL
                and runner_cell.implementation is CellImplementation.UNSUPPORTED
            ):
                plans.append(
                    MatrixCellPlan(
                        agent=agent,
                        backend=backend,
                        status="unsupported",
                        rationale=runner_cell.rationale,
                        run=False,
                    )
                )
                continue

            config = BenchmarkRunConfig(
                family=BenchmarkFamily.LOCOMO,
                agent=agent,
                backend=backend,
                use_mock_agent=use_mock_agent,
            )
            supported, rationale = is_supported_coordinate(config)
            if not supported:
                plans.append(
                    MatrixCellPlan(
                        agent=agent,
                        backend=backend,
                        status="unsupported",
                        rationale=rationale,
                        run=False,
                    )
                )
                continue

            plans.append(
                MatrixCellPlan(
                    agent=agent,
                    backend=backend,
                    status="runnable",
                    rationale=runner_cell.rationale,
                    run=True,
                    runner_mode=runner_mode,
                )
            )
    return plans


def build_locomo_run_config(
    plan: MatrixCellPlan,
    *,
    dataset_id: str,
    dataset_version: str,
    seed: int,
    top_k: int,
    runner_mode: MatrixRunnerMode,
    max_conversations: int | None,
    agent_executable: str | None = None,
    agent_timeout_s: float = 120.0,
) -> BenchmarkRunConfig:
    return BenchmarkRunConfig(
        family=BenchmarkFamily.LOCOMO,
        agent=plan.agent,
        backend=plan.backend,
        seed=seed,
        top_k=top_k,
        resume=False,
        use_mock_agent=runner_mode is MatrixRunnerMode.MOCK,
        agent_executable=agent_executable,
        agent_timeout_s=agent_timeout_s,
        dataset_id=dataset_id,
        dataset_version=dataset_version,
        max_conversations=max_conversations,
    )


def build_matrix_command(
    *,
    runner_mode: MatrixRunnerMode,
    output_root: Path,
    dataset_id: str,
    dataset_version: str | None,
    seed: int,
    top_k: int,
    max_conversations: int | None,
    include_openclaw: bool,
    agent_executable: str | None,
    agent_timeout_s: float,
) -> str:
    """Return a reproducible shell command for this matrix invocation."""
    argv = [
        sys.executable,
        str(Path("scripts") / "run_locomo_matrix.py"),
        "--output-dir",
        str(output_root),
        "--dataset-id",
        dataset_id,
        "--seed",
        str(seed),
        "--top-k",
        str(top_k),
        "--runner-mode",
        runner_mode.value,
    ]
    if dataset_version:
        argv.extend(["--dataset-version", dataset_version])
    if max_conversations is not None:
        argv.extend(["--max-conversations", str(max_conversations)])
    if include_openclaw:
        argv.append("--include-openclaw")
    if agent_executable:
        argv.extend(["--agent-executable", agent_executable])
    if agent_timeout_s != 120.0:
        argv.extend(["--agent-timeout-s", str(agent_timeout_s)])
    return " ".join(shlex.quote(part) for part in argv)


def _summarize_completed_cell(
    result: BenchmarkRunResult,
    *,
    plan: MatrixCellPlan,
    output_root: Path,
) -> dict[str, Any]:
    coordinate = matrix_key(plan.agent, plan.backend)
    runner_mode = (
        "mock_only"
        if result.config.use_mock_agent
        else result.agent_metadata.get("runtime_provenance", {})
        .get("cli_mode", "real")
    )
    cell: dict[str, Any] = {
        "coordinate": coordinate,
        "agent": plan.agent.value,
        "backend": plan.backend.value,
        "status": result.agent_metadata.get("status", "completed"),
        "rationale": plan.rationale,
        "runner_mode": runner_mode,
        "run_id": result.run_id,
        "summary_path": str(output_root / result.run_id / "summary.json"),
        "queries_jsonl_path": str(output_root / result.run_id / "queries.jsonl"),
        "invocations_jsonl_path": str(output_root / result.run_id / "invocations.jsonl"),
        "mean_accuracy": result.aggregates.mean_accuracy,
        "mean_retrieval_hit_rate": result.aggregates.mean_retrieval_hit_rate,
        "mean_query_time_ms": result.timing_aggregates.get("mean_query_time_ms"),
        "p95_query_time_ms": result.timing_aggregates.get("p95_query_time_ms"),
        "total_input_tokens": result.aggregates.total_input_tokens,
        "mean_input_tokens": result.timing_aggregates.get("mean_input_tokens"),
        "total_failure_count": result.aggregates.total_failure_count,
        "token_source_counts": token_source_aggregates(result.queries),
        "category_aggregates": result.category_aggregates,
        "runtime_provenance": result.agent_metadata.get("runtime_provenance"),
        "environment": result.environment,
    }
    if result.queries:
        sample = result.queries[0]
        if sample.agent_metadata.get("argv"):
            cell["sample_argv"] = sample.agent_metadata["argv"]
    return cell


def run_locomo_matrix(
    *,
    output_root: Path,
    dataset_id: str = "locomo10",
    dataset_version: str | None = None,
    seed: int = 0,
    top_k: int = 5,
    runner_mode: MatrixRunnerMode = MatrixRunnerMode.MOCK,
    include_openclaw: bool = False,
    max_conversations: int | None = None,
    agent_executable: str | None = None,
    agent_timeout_s: float = 120.0,
) -> dict[str, Any]:
    """Execute or annotate every LoCoMo matrix cell."""
    manifest = get_dataset_manifest(dataset_id)
    version = dataset_version or manifest.version
    plans = locomo_matrix_plans(
        include_openclaw=include_openclaw,
        runner_mode=runner_mode,
    )
    harness = CrossAgentBenchmarkHarness(output_root=output_root)

    cells: list[dict[str, Any]] = []
    completed_cells: list[dict[str, Any]] = []
    results: list[BenchmarkRunResult] = []

    for plan in plans:
        coordinate = matrix_key(plan.agent, plan.backend)
        if not plan.run:
            cell = {
                "coordinate": coordinate,
                "agent": plan.agent.value,
                "backend": plan.backend.value,
                "status": plan.status,
                "rationale": plan.rationale,
            }
            cells.append(cell)
            continue

        config = build_locomo_run_config(
            plan,
            dataset_id=dataset_id,
            dataset_version=version,
            seed=seed,
            top_k=top_k,
            runner_mode=runner_mode,
            max_conversations=max_conversations,
            agent_executable=agent_executable,
            agent_timeout_s=agent_timeout_s,
        )
        try:
            assert_supported(config.backend, config.agent)
        except UnsupportedCombinationError as exc:
            cell = {
                "coordinate": coordinate,
                "agent": plan.agent.value,
                "backend": plan.backend.value,
                "status": "unsupported",
                "rationale": str(exc),
            }
            cells.append(cell)
            continue

        result = harness.run(config)
        results.append(result)
        cell = _summarize_completed_cell(result, plan=plan, output_root=output_root)
        cells.append(cell)
        completed_cells.append(cell)

    exact_command = build_matrix_command(
        runner_mode=runner_mode,
        output_root=output_root,
        dataset_id=dataset_id,
        dataset_version=version,
        seed=seed,
        top_k=top_k,
        max_conversations=max_conversations,
        include_openclaw=include_openclaw,
        agent_executable=agent_executable,
        agent_timeout_s=agent_timeout_s,
    )

    report_type = (
        "mock_smoke"
        if runner_mode is MatrixRunnerMode.MOCK
        else "real_cli_comparison"
    )
    summary = {
        "benchmark": "locomo_cross_agent_memory",
        "report_type": report_type,
        "runner_mode": runner_mode.value,
        "provenance": {
            "exact_command": exact_command,
            "argv": shlex.split(exact_command),
            "python": sys.version.split()[0],
        },
        "dataset": {
            **manifest.to_dict(),
            "dataset_version": version,
            "max_conversations": max_conversations,
        },
        "matrix": {
            "agents": [agent.value for agent in LOCOMO_AGENTS],
            "backends": [backend.value for backend in LOCOMO_BACKENDS],
            "include_openclaw": include_openclaw,
            "runner_mode": runner_mode.value,
            "seed": seed,
            "top_k": top_k,
            "agent_executable": agent_executable,
            "agent_timeout_s": agent_timeout_s,
        },
        "cells": cells,
        "completed_run_count": len(completed_cells),
        "unsupported_or_pending_count": sum(
            1 for cell in cells if cell["status"] in {"unsupported", "pending"}
        ),
    }
    if runner_mode is MatrixRunnerMode.MOCK:
        summary["mock_results"] = completed_cells
        summary["notes"] = (
            "Mock results are offline smoke tests only. They do not represent "
            "cross-agent production CLI comparisons. Run with --runner-mode real "
            "for Hermes/Claude/Codex CLI metrics."
        )
    else:
        summary["real_results"] = completed_cells
        summary["notes"] = (
            "Real CLI results invoke production agent boundaries. Unsupported "
            "cells are listed explicitly and were not executed."
        )
    return summary
