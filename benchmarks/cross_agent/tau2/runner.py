"""tau2-bench agent-experience comparison runner (HM-76 / MEM-76)."""

from __future__ import annotations

import json
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from ..agents.registry import is_supported_coordinate
from ..agents.workspace import AgentWorkspace
from ..backends.mem0 import Mem0Backend, OfflineMem0Client
from ..backends.openviking import OfflineOpenVikingClient, OpenVikingBackend
from ..backends.registry import create_memory_backend
from ..protocol import MemoryBackend
from ..run_id import resolve_run_id
from ..runner import CrossAgentBenchmarkHarness
from ..types import (
    AgentKind,
    BenchmarkFamily,
    BenchmarkRunConfig,
    MemoryBackendKind,
    SyntheticFixture,
)
from .agent_cli import classify_cli_failure, is_harness_executable, production_cli_status
from .agent_loop import HARNESS_AGENT_LABEL, run_domain_agent_loop
from .availability import tau2_runtime_info
from .config import (
    DOMAIN_SEEDS,
    Tau2ComparisonConfig,
    Tau2ComparisonMode,
    Tau2Domain,
    Tau2MatrixCoordinate,
    cell_support_rationale,
    tau2_matrix_coordinates,
)
from .fixtures import get_tau2_domain_fixture
from .loader import load_real_domain_tasks
from .summary import Tau2ComparisonReport, build_summary_table, write_comparison_artifacts
from .trajectories import append_trajectory_index, write_agent_loop_trajectory
from .types import Tau2CellResult, Tau2DomainRun, aggregate_agent_executions


@contextmanager
def _patch_tau2_fixture(
    domain: Tau2Domain,
    fixture: SyntheticFixture,
) -> Iterator[None]:
    """Temporarily route tau2_bench family loads to the active domain fixture."""
    from benchmarks.cross_agent import runner as runner_module
    from benchmarks.cross_agent.fixtures import synthetic as synthetic_module

    original_fixture_loader = synthetic_module.get_synthetic_fixture
    original_runner_loader = runner_module.get_synthetic_fixture

    def patched(family: BenchmarkFamily):
        if family is BenchmarkFamily.TAU2_BENCH:
            return fixture
        return original_fixture_loader(family)

    synthetic_module.get_synthetic_fixture = patched  # type: ignore[assignment]
    runner_module.get_synthetic_fixture = patched  # type: ignore[assignment]
    try:
        yield
    finally:
        synthetic_module.get_synthetic_fixture = original_fixture_loader  # type: ignore[assignment]
        runner_module.get_synthetic_fixture = original_runner_loader  # type: ignore[assignment]


def _create_backend(
    backend: MemoryBackendKind,
    agent: AgentKind,
    *,
    namespace: str,
) -> MemoryBackend:
    if backend is MemoryBackendKind.MEM0:
        return Mem0Backend(client=OfflineMem0Client(user_id=namespace))
    if backend is MemoryBackendKind.OPENVIKING:
        return OpenVikingBackend(client=OfflineOpenVikingClient(namespace=namespace))
    return create_memory_backend(backend, agent=agent)


def _run_smoke_domain_cell(
    coordinate: Tau2MatrixCoordinate,
    domain: Tau2Domain,
    *,
    comparison: Tau2ComparisonConfig,
    output_root: Path,
    trajectories_dir: Path,
) -> Tau2DomainRun:
    fixture = get_tau2_domain_fixture(domain, mode=comparison.mode)
    seed = DOMAIN_SEEDS[domain]
    config = BenchmarkRunConfig(
        family=BenchmarkFamily.TAU2_BENCH,
        agent=coordinate.agent,
        backend=coordinate.backend,
        seed=seed,
        top_k=comparison.top_k,
        resume=False,
        use_mock_agent=True,
    )
    namespace = f"tau2-{domain.value}-{coordinate.agent.value}-{coordinate.backend.value}"

    with _patch_tau2_fixture(domain, fixture):
        backend = _create_backend(
            coordinate.backend,
            coordinate.agent,
            namespace=namespace,
        )
        harness = CrossAgentBenchmarkHarness(output_root=output_root, backend=backend)
        result = harness.run(config)

    trajectory_path = trajectories_dir / f"{result.run_id}.jsonl"
    from .trajectories import write_run_trajectory

    write_run_trajectory(
        trajectory_path,
        domain=domain,
        result=result,
        fixture=fixture,
        comparison=comparison,
        env_executions=[],
    )
    return Tau2DomainRun(
        domain=domain,
        result=result,
        trajectory_path=str(trajectory_path),
        run_id=result.run_id,
    )


def _run_agent_loop_domain_cell(
    coordinate: Tau2MatrixCoordinate,
    domain: Tau2Domain,
    *,
    comparison: Tau2ComparisonConfig,
    output_root: Path,
    trajectories_dir: Path,
) -> Tau2DomainRun:
    tasks = load_real_domain_tasks(
        domain,
        task_split_name=comparison.task_split_name,
        num_tasks=comparison.num_tasks,
    )
    seed = DOMAIN_SEEDS[domain]
    use_harness_agent = (
        comparison.mode is Tau2ComparisonMode.HARNESS or comparison.use_harness_agent
    )
    agent_executable = comparison.agent_executable
    if agent_executable:
        agent_executable = str(Path(agent_executable).resolve())
    config = BenchmarkRunConfig(
        family=BenchmarkFamily.TAU2_BENCH,
        agent=coordinate.agent,
        backend=coordinate.backend,
        seed=seed,
        top_k=comparison.top_k,
        resume=False,
        use_mock_agent=False,
        agent_executable=agent_executable,
    )
    run_id = resolve_run_id(config)
    run_dir = output_root / run_id
    storage_dir = run_dir / "storage"
    storage_dir.mkdir(parents=True, exist_ok=True)
    namespace = f"tau2-{domain.value}-{coordinate.agent.value}-{coordinate.backend.value}"

    workspace = AgentWorkspace.create(
        coordinate.agent,
        run_id=run_id,
        parent=run_dir,
    )
    backend = _create_backend(
        coordinate.backend,
        coordinate.agent,
        namespace=namespace,
    )
    backend.open(storage_dir, config)
    try:
        agent_executions = run_domain_agent_loop(
            domain,
            tasks,
            agent=coordinate.agent,
            config=config,
            workspace=workspace,
            storage_dir=storage_dir,
            backend=backend,
            executable=agent_executable,
            use_harness_agent=use_harness_agent,
            user_mode="scripted" if use_harness_agent else comparison.user_mode,
            user_llm=comparison.user_llm,
            user_cli=comparison.user_cli,
            user_cli_executable=comparison.user_cli_executable,
        )
        if comparison.consolidate_memory:
            backend.consolidate()
    finally:
        backend.close()
        workspace.cleanup()

    metrics = aggregate_agent_executions(agent_executions)
    trajectory_path = trajectories_dir / f"{run_id}.jsonl"
    write_agent_loop_trajectory(
        trajectory_path,
        domain=domain,
        coordinate=coordinate,
        comparison=comparison,
        run_id=run_id,
        agent_executions=agent_executions,
        metrics=metrics,
    )
    return Tau2DomainRun(
        domain=domain,
        trajectory_path=str(trajectory_path),
        agent_executions=agent_executions,
        metrics=metrics,
        run_id=run_id,
    )


def _resolve_cell_status(
    coordinate: Tau2MatrixCoordinate,
    *,
    comparison: Tau2ComparisonConfig,
) -> tuple[str, str | None]:
    backend_supported, backend_reason = cell_support_rationale(
        coordinate.agent,
        coordinate.backend,
    )
    if not backend_supported:
        return "unsupported", backend_reason

    if comparison.mode is Tau2ComparisonMode.SMOKE:
        config = BenchmarkRunConfig(
            family=BenchmarkFamily.TAU2_BENCH,
            agent=coordinate.agent,
            backend=coordinate.backend,
            seed=0,
            use_mock_agent=True,
        )
        runner_supported, runner_reason = is_supported_coordinate(config)
        if not runner_supported:
            return "unsupported", runner_reason
        return "completed", runner_reason

    config = BenchmarkRunConfig(
        family=BenchmarkFamily.TAU2_BENCH,
        agent=coordinate.agent,
        backend=coordinate.backend,
        seed=0,
        use_mock_agent=False,
        agent_executable=comparison.agent_executable,
    )
    runner_supported, runner_reason = is_supported_coordinate(config)
    if not runner_supported:
        return "unsupported", runner_reason

    if comparison.mode is Tau2ComparisonMode.HARNESS:
        if not comparison.use_harness_agent and not comparison.agent_executable:
            return (
                "failed",
                "HARNESS mode requires --use-harness-agent or --agent-executable",
            )
        if comparison.agent_executable and not is_harness_executable(
            comparison.agent_executable
        ):
            return (
                "failed",
                "HARNESS mode requires a labeled fake tau2 CLI executable",
            )
        return "completed", runner_reason

    invalid_real = comparison.validate_real_mode()
    if invalid_real is not None:
        return invalid_real

    cli_status, cli_reason = production_cli_status(
        coordinate.agent,
        executable_override=comparison.agent_executable,
    )
    if cli_status != "ready":
        return cli_status, cli_reason

    return "completed", cli_reason


def _detect_execution_failure(domain_run: Tau2DomainRun) -> str | None:
    """Return an execution failure message for REAL-mode domain runs."""
    if domain_run.error:
        return domain_run.error
    for execution in domain_run.agent_executions:
        if execution.error:
            return execution.error
        for step in execution.steps:
            if step.error:
                return step.error
            if step.exit_code != 0:
                detail = step.stderr.strip() or step.stdout.strip() or f"exit {step.exit_code}"
                return f"agent CLI step failed: {detail}"
    return None


def _detect_auth_failure(domain_run: Tau2DomainRun) -> str | None:
    """Return an auth/login failure message when agent CLI output indicates one."""
    for execution in domain_run.agent_executions:
        if execution.error:
            failure = classify_cli_failure(execution.error)
            if failure:
                return f"{failure}: {execution.error}"
        for step in execution.steps:
            failure = classify_cli_failure(step.stderr, step.stdout)
            if failure:
                detail = step.stderr.strip() or step.stdout.strip() or step.error or ""
                return f"{failure}: {detail}"
    return None


def _write_provenance(output_root: Path, comparison: Tau2ComparisonConfig) -> None:
    payload = {
        "issue": "MEM-76",
        **comparison.provenance(),
        **tau2_runtime_info(),
    }
    (output_root / "provenance.json").write_text(
        json.dumps(payload, indent=2, default=str),
        encoding="utf-8",
    )


def run_tau2_comparison(
    config: Tau2ComparisonConfig | None = None,
    *,
    output_root: Path | None = None,
) -> Tau2ComparisonReport:
    """Execute the tau2-bench agent-experience matrix and write artifacts."""
    comparison = config or Tau2ComparisonConfig()
    root = Path(output_root or comparison.output_root).resolve()
    runs_root = root / "runs"
    trajectories_dir = root / "trajectories"
    trajectories_dir.mkdir(parents=True, exist_ok=True)
    trajectory_index = root / "trajectory_index.jsonl"
    if trajectory_index.exists():
        trajectory_index.unlink()

    cell_results: list[Tau2CellResult] = []

    for coordinate in tau2_matrix_coordinates():
        status, rationale = _resolve_cell_status(
            coordinate,
            comparison=comparison,
        )
        cell = Tau2CellResult(
            coordinate=coordinate,
            status=status,
            rationale=rationale,
        )

        if status == "completed":
            for domain in comparison.domains:
                try:
                    if comparison.mode is Tau2ComparisonMode.SMOKE:
                        domain_run = _run_smoke_domain_cell(
                            coordinate,
                            domain,
                            comparison=comparison,
                            output_root=runs_root,
                            trajectories_dir=trajectories_dir,
                        )
                    else:
                        domain_run = _run_agent_loop_domain_cell(
                            coordinate,
                            domain,
                            comparison=comparison,
                            output_root=runs_root,
                            trajectories_dir=trajectories_dir,
                        )
                    if comparison.mode is Tau2ComparisonMode.REAL:
                        auth_failure = _detect_auth_failure(domain_run)
                        if auth_failure is not None:
                            cell.status = "failed"
                            cell.rationale = auth_failure
                            cell.domain_results[domain] = Tau2DomainRun(
                                domain=domain,
                                error=auth_failure,
                                trajectory_path=domain_run.trajectory_path,
                                agent_executions=domain_run.agent_executions,
                                metrics=domain_run.metrics,
                                run_id=domain_run.run_id,
                            )
                            continue
                        exec_failure = _detect_execution_failure(domain_run)
                        if exec_failure is not None:
                            cell.status = "failed"
                            cell.rationale = exec_failure
                    cell.domain_results[domain] = domain_run
                    append_trajectory_index(
                        trajectory_index,
                        [
                            {
                                "run_id": domain_run.run_id
                                or (
                                    domain_run.result.run_id
                                    if domain_run.result
                                    else None
                                ),
                                "domain": domain.value,
                                "agent": coordinate.agent.value,
                                "backend": coordinate.backend.value,
                                "trajectory_path": domain_run.trajectory_path,
                                "mode": comparison.mode.value,
                                "harness_label": (
                                    HARNESS_AGENT_LABEL
                                    if comparison.mode is Tau2ComparisonMode.HARNESS
                                    or comparison.use_harness_agent
                                    else None
                                ),
                            }
                        ],
                    )
                except Exception as exc:  # noqa: BLE001 — record cell failure
                    cell.status = "failed"
                    cell.domain_results[domain] = Tau2DomainRun(
                        domain=domain,
                        error=str(exc),
                    )

        cell_results.append(cell)

    report = build_summary_table(cell_results, comparison=comparison)
    write_comparison_artifacts(root, report)
    _write_provenance(root, comparison)
    return report
