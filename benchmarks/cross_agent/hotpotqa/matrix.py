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
from .cells import CellStatus, HotpotqaMatrixCell, iter_hotpotqa_matrix_cells, runnable_cells
from .evidence import supporting_facts_index, write_retrieval_evidence
from .manifest import (
    ResolvedExecutable,
    build_run_manifest,
    collect_agent_executables,
    write_run_manifest,
)
from .summary import build_matrix_summary, summarize_cell, write_matrix_summary

CLI_UNAVAILABLE_RATIONALE = (
    "Agent CLI executable not found on PATH; install the host agent "
    "(codex, claude, hermes) and re-run with --use-real-cli."
)
TEST_DOUBLE_ONLY_RATIONALE = (
    "Comparison runs require a host agent CLI; test-double invocations belong in "
    "benchmark-results/hotpotqa-smoke or tests with allow_test_double=True."
)


@dataclass
class HotpotqaMatrixRunOutcome:
    cell: HotpotqaMatrixCell
    result: BenchmarkRunResult | None
    run_dir: Path | None
    pending_rationale: str | None = None


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


def _write_pending_placeholder(
    output_root: Path,
    cell: HotpotqaMatrixCell,
    *,
    seed: int,
    rationale: str | None = None,
) -> Path:
    pending_dir = output_root / "pending" / f"{cell.agent.value}-{cell.backend.value}-k{cell.top_k}"
    pending_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "status": CellStatus.PENDING.value,
        "agent": cell.agent.value,
        "backend": cell.backend.value,
        "top_k": cell.top_k,
        "seed": seed,
        "rationale": rationale or cell.rationale,
    }
    (pending_dir / "status.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return pending_dir


def _comparison_executable(
    cell: HotpotqaMatrixCell,
    agent_executables: dict[str, ResolvedExecutable | None],
    *,
    allow_test_double: bool,
) -> tuple[ResolvedExecutable | None, str | None]:
    """Return the resolved CLI for a comparison cell, or a pending rationale."""
    resolved = agent_executables.get(cell.agent.value)
    if resolved is None:
        return None, CLI_UNAVAILABLE_RATIONALE
    if resolved.is_test_double and not allow_test_double:
        return None, TEST_DOUBLE_ONLY_RATIONALE
    return resolved, None


def run_hotpotqa_matrix(
    *,
    output_root: Path,
    seed: int = 0,
    use_mock_agent: bool = False,
    agent_executable: str | None = None,
    allow_test_double: bool = False,
    execution_mode: str = "comparison",
    command: str | None = None,
) -> dict[str, Any]:
    """Execute the HotpotQA matrix and write cross-run summary artifacts."""
    output_root.mkdir(parents=True, exist_ok=True)
    supporting_facts = supporting_facts_index()
    outcomes: list[HotpotqaMatrixRunOutcome] = []
    harness = CrossAgentBenchmarkHarness(output_root=output_root)

    participating_agents = tuple(
        {cell.agent for cell in iter_hotpotqa_matrix_cells() if cell.status is CellStatus.RUN}
    )
    agent_executables = (
        {}
        if use_mock_agent
        else collect_agent_executables(
            participating_agents,
            override=agent_executable,
            allow_test_double=allow_test_double,
        )
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
        if cell.status is CellStatus.RUN:
            if use_mock_agent:
                cell_executable = None
                pending_rationale = None
            else:
                resolved, pending_rationale = _comparison_executable(
                    cell,
                    agent_executables,
                    allow_test_double=allow_test_double,
                )
                if pending_rationale is not None:
                    pending_dir = _write_pending_placeholder(
                        output_root,
                        cell,
                        seed=seed,
                        rationale=pending_rationale,
                    )
                    outcomes.append(
                        HotpotqaMatrixRunOutcome(
                            cell=cell,
                            result=None,
                            run_dir=pending_dir,
                            pending_rationale=pending_rationale,
                        )
                    )
                    continue
                cell_executable = resolved.path if resolved is not None else None

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
            pending_rationale=outcome.pending_rationale,
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
    return len(runnable_cells())
