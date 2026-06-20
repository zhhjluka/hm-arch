"""HotpotQA matrix execution for MEM-77."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..runner import CrossAgentBenchmarkHarness, run_cross_agent_benchmark
from ..types import (
    AgentKind,
    BenchmarkFamily,
    BenchmarkRunConfig,
    BenchmarkRunResult,
    MemoryBackendKind,
)
from .cells import CellStatus, HotpotqaMatrixCell, iter_hotpotqa_matrix_cells, runnable_non_openclaw_cells
from .evidence import supporting_facts_index, write_retrieval_evidence
from .manifest import build_run_manifest, collect_agent_executables, write_run_manifest
from .summary import build_matrix_summary, summarize_cell, write_matrix_summary


@dataclass
class HotpotqaMatrixRunOutcome:
    cell: HotpotqaMatrixCell
    result: BenchmarkRunResult | None
    run_dir: Path | None


def _config_for_cell(
    cell: HotpotqaMatrixCell,
    *,
    seed: int,
    use_mock_agent: bool,
    agent_executable: str | None,
) -> BenchmarkRunConfig:
    return BenchmarkRunConfig(
        family=BenchmarkFamily.HOTPOTQA,
        agent=cell.agent,
        backend=cell.backend,
        seed=seed,
        top_k=cell.top_k,
        resume=False,
        use_mock_agent=use_mock_agent,
        agent_executable=agent_executable,
    )


def _run_unsupported_cell(
    cell: HotpotqaMatrixCell,
    *,
    output_root: Path,
    seed: int,
    use_mock_agent: bool,
    agent_executable: str | None,
) -> BenchmarkRunResult | None:
    if cell.status is CellStatus.UNSUPPORTED:
        return None
    config = _config_for_cell(
        cell,
        seed=seed,
        use_mock_agent=use_mock_agent,
        agent_executable=agent_executable,
    )
    return run_cross_agent_benchmark(config, output_root=output_root)


def _write_pending_placeholder(output_root: Path, cell: HotpotqaMatrixCell, *, seed: int) -> Path:
    pending_dir = output_root / "pending" / f"{cell.agent.value}-{cell.backend.value}-k{cell.top_k}"
    pending_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "status": CellStatus.PENDING.value,
        "agent": cell.agent.value,
        "backend": cell.backend.value,
        "top_k": cell.top_k,
        "seed": seed,
        "rationale": cell.rationale,
    }
    (pending_dir / "status.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return pending_dir


def run_hotpotqa_matrix(
    *,
    output_root: Path,
    seed: int = 0,
    use_mock_agent: bool = False,
    include_openclaw: bool = False,
    agent_executable: str | None = None,
    execution_mode: str = "comparison",
    command: str | None = None,
) -> dict[str, Any]:
    """Execute the HotpotQA matrix and write cross-run summary artifacts."""
    output_root.mkdir(parents=True, exist_ok=True)
    supporting_facts = supporting_facts_index()
    outcomes: list[HotpotqaMatrixRunOutcome] = []
    harness = CrossAgentBenchmarkHarness(output_root=output_root)

    participating_agents = tuple(
        {
            cell.agent
            for cell in iter_hotpotqa_matrix_cells()
            if cell.status is CellStatus.RUN
            or (
                cell.agent is AgentKind.OPENCLAW
                and include_openclaw
                and cell.status is not CellStatus.UNSUPPORTED
            )
        }
    )
    agent_executables = (
        {}
        if use_mock_agent
        else collect_agent_executables(participating_agents, override=agent_executable)
    )

    run_command = command or (
        "uv run python scripts/run_hotpotqa_matrix.py"
        + (" --mock-smoke" if use_mock_agent else " --use-real-cli")
        + (f" --output-dir {output_root}" if str(output_root) != "benchmark-results/hotpotqa" else "")
    )
    write_run_manifest(
        output_root / "run_manifest.json",
        build_run_manifest(
            output_root=output_root,
            seed=seed,
            execution_mode=execution_mode,
            use_mock_agent=use_mock_agent,
            command=run_command,
            agent_executables=agent_executables or None,
        ),
    )

    for cell in iter_hotpotqa_matrix_cells():
        if cell.agent is AgentKind.OPENCLAW and not include_openclaw:
            if cell.status is CellStatus.PENDING:
                pending_dir = _write_pending_placeholder(output_root, cell, seed=seed)
                outcomes.append(HotpotqaMatrixRunOutcome(cell=cell, result=None, run_dir=pending_dir))
            else:
                result = _run_unsupported_cell(
                    cell,
                    output_root=output_root,
                    seed=seed,
                    use_mock_agent=use_mock_agent,
                    agent_executable=agent_executable,
                )
                run_dir = output_root / result.run_id if result is not None else None
                outcomes.append(HotpotqaMatrixRunOutcome(cell=cell, result=result, run_dir=run_dir))
            continue

        if cell.status is CellStatus.RUN:
            cell_executable = None if use_mock_agent else agent_executables[cell.agent.value].path
            config = _config_for_cell(
                cell,
                seed=seed,
                use_mock_agent=use_mock_agent,
                agent_executable=cell_executable,
            )
            result = harness.run(config)
            run_dir = output_root / result.run_id
            write_retrieval_evidence(run_dir, result, supporting_facts_by_query=supporting_facts)
            outcomes.append(HotpotqaMatrixRunOutcome(cell=cell, result=result, run_dir=run_dir))
            continue

        result = _run_unsupported_cell(
            cell,
            output_root=output_root,
            seed=seed,
            use_mock_agent=use_mock_agent,
            agent_executable=agent_executable,
        )
        run_dir = output_root / result.run_id if result is not None else None
        outcomes.append(HotpotqaMatrixRunOutcome(cell=cell, result=result, run_dir=run_dir))

    cell_summaries = [
        summarize_cell(
            outcome.cell,
            result=outcome.result,
            run_dir=outcome.run_dir,
            execution_mode=execution_mode,
            agent_executable=(
                None
                if use_mock_agent
                else agent_executables.get(outcome.cell.agent.value)
            ),
        )
        for outcome in outcomes
    ]
    summary_payload = build_matrix_summary(
        cell_summaries=cell_summaries,
        output_root=output_root,
        execution_mode=execution_mode,
        use_mock_agent=use_mock_agent,
        command=run_command,
        agent_executables=agent_executables or None,
    )
    write_matrix_summary(output_root / "matrix_summary.json", summary_payload)
    return summary_payload


def expected_runnable_cell_count() -> int:
    return len(runnable_non_openclaw_cells())
