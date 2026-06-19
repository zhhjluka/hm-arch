"""LoCoMo cross-agent memory comparison matrix (MEM-78 / HM-75)."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .agents.registry import is_supported_coordinate
from .compatibility import (
    UnsupportedCombinationError,
    assert_supported,
    compatibility_cell,
    lookup_matrix_cell,
    matrix_key,
)
from .fixtures.locomo.loader import get_dataset_manifest
from .runner import CrossAgentBenchmarkHarness
from .types import AgentKind, BenchmarkFamily, BenchmarkRunConfig, BenchmarkRunResult, MemoryBackendKind


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


def locomo_matrix_plans(
    *,
    include_openclaw: bool = False,
    use_mock_agent: bool = True,
) -> list[MatrixCellPlan]:
    """Return the full LoCoMo matrix with explicit unsupported/pending notes."""
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

            if not use_mock_agent and runner_cell.implementation.value == "unsupported":
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
    use_mock_agent: bool,
    max_conversations: int | None,
) -> BenchmarkRunConfig:
    return BenchmarkRunConfig(
        family=BenchmarkFamily.LOCOMO,
        agent=plan.agent,
        backend=plan.backend,
        seed=seed,
        top_k=top_k,
        resume=False,
        use_mock_agent=use_mock_agent,
        dataset_id=dataset_id,
        dataset_version=dataset_version,
        max_conversations=max_conversations,
    )


def run_locomo_matrix(
    *,
    output_root: Path,
    dataset_id: str = "locomo10",
    dataset_version: str | None = None,
    seed: int = 0,
    top_k: int = 5,
    use_mock_agent: bool = True,
    include_openclaw: bool = False,
    max_conversations: int | None = None,
) -> dict[str, Any]:
    """Execute or annotate every LoCoMo matrix cell."""
    manifest = get_dataset_manifest(dataset_id)
    version = dataset_version or manifest.version
    plans = locomo_matrix_plans(
        include_openclaw=include_openclaw,
        use_mock_agent=use_mock_agent,
    )
    harness = CrossAgentBenchmarkHarness(output_root=output_root)

    cells: list[dict[str, Any]] = []
    results: list[BenchmarkRunResult] = []

    for plan in plans:
        coordinate = matrix_key(plan.agent, plan.backend)
        if not plan.run:
            cells.append(
                {
                    "coordinate": coordinate,
                    "agent": plan.agent.value,
                    "backend": plan.backend.value,
                    "status": plan.status,
                    "rationale": plan.rationale,
                }
            )
            continue

        config = build_locomo_run_config(
            plan,
            dataset_id=dataset_id,
            dataset_version=version,
            seed=seed,
            top_k=top_k,
            use_mock_agent=use_mock_agent,
            max_conversations=max_conversations,
        )
        try:
            assert_supported(config.backend, config.agent)
        except UnsupportedCombinationError as exc:
            cells.append(
                {
                    "coordinate": coordinate,
                    "agent": plan.agent.value,
                    "backend": plan.backend.value,
                    "status": "unsupported",
                    "rationale": str(exc),
                }
            )
            continue

        result = harness.run(config)
        results.append(result)
        cells.append(
            {
                "coordinate": coordinate,
                "agent": plan.agent.value,
                "backend": plan.backend.value,
                "status": result.agent_metadata.get("status", "completed"),
                "rationale": plan.rationale,
                "run_id": result.run_id,
                "summary_path": str(output_root / result.run_id / "summary.json"),
                "queries_jsonl_path": str(output_root / result.run_id / "queries.jsonl"),
                "mean_accuracy": result.aggregates.mean_accuracy,
                "mean_retrieval_hit_rate": result.aggregates.mean_retrieval_hit_rate,
                "mean_query_time_ms": result.timing_aggregates.get("mean_query_time_ms"),
                "p95_query_time_ms": result.timing_aggregates.get("p95_query_time_ms"),
                "total_input_tokens": result.aggregates.total_input_tokens,
                "mean_input_tokens": result.timing_aggregates.get("mean_input_tokens"),
                "total_failure_count": result.aggregates.total_failure_count,
                "category_aggregates": result.category_aggregates,
            }
        )

    summary = {
        "benchmark": "locomo_cross_agent_memory",
        "dataset": {
            **manifest.to_dict(),
            "dataset_version": version,
            "max_conversations": max_conversations,
        },
        "matrix": {
            "agents": [agent.value for agent in LOCOMO_AGENTS],
            "backends": [backend.value for backend in LOCOMO_BACKENDS],
            "include_openclaw": include_openclaw,
            "use_mock_agent": use_mock_agent,
            "seed": seed,
            "top_k": top_k,
        },
        "cells": cells,
        "completed_run_count": sum(1 for cell in cells if cell.get("run_id")),
        "unsupported_or_pending_count": sum(
            1 for cell in cells if cell["status"] in {"unsupported", "pending"}
        ),
    }
    return summary
