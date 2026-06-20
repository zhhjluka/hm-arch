"""tau2-bench agent-experience comparison runner (HM-76 / MEM-76)."""

from __future__ import annotations

import json
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from ..agents.registry import is_supported_coordinate
from ..backends.mem0 import Mem0Backend, OfflineMem0Client
from ..backends.openviking import OfflineOpenVikingClient, OpenVikingBackend
from ..backends.registry import create_memory_backend
from ..protocol import MemoryBackend
from ..runner import CrossAgentBenchmarkHarness
from ..types import (
    AgentKind,
    BenchmarkFamily,
    BenchmarkRunConfig,
    BenchmarkRunResult,
    MemoryBackendKind,
    SyntheticFixture,
)
from .availability import tau2_runtime_info
from .config import (
    DOMAIN_SEEDS,
    OPENCLAW_PENDING_ISSUE,
    Tau2ComparisonConfig,
    Tau2ComparisonMode,
    Tau2Domain,
    Tau2MatrixCoordinate,
    cell_support_rationale,
    tau2_matrix_coordinates,
)
from .environment_runner import Tau2EnvironmentExecution
from .fixtures import get_tau2_domain_fixture
from .loader import load_real_domain_fixture
from .summary import Tau2ComparisonReport, build_summary_table, write_comparison_artifacts
from .trajectories import append_trajectory_index, write_run_trajectory
from .types import Tau2CellResult, Tau2DomainRun


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


def _resolve_domain_fixture(
    domain: Tau2Domain,
    comparison: Tau2ComparisonConfig,
    *,
    env_cache: dict[Tau2Domain, tuple[SyntheticFixture, list[Tau2EnvironmentExecution]]],
) -> tuple[SyntheticFixture, list[Tau2EnvironmentExecution]]:
    if comparison.mode is Tau2ComparisonMode.SMOKE:
        fixture = get_tau2_domain_fixture(domain, mode=comparison.mode)
        return fixture, []
    if domain not in env_cache:
        fixture, executions = load_real_domain_fixture(
            domain,
            task_split_name=comparison.task_split_name,
            num_tasks=comparison.num_tasks,
        )
        env_cache[domain] = (fixture, executions)
    return env_cache[domain]


def _run_domain_cell(
    coordinate: Tau2MatrixCoordinate,
    domain: Tau2Domain,
    *,
    comparison: Tau2ComparisonConfig,
    output_root: Path,
    trajectories_dir: Path,
    fixture: SyntheticFixture,
    env_executions: list[Tau2EnvironmentExecution],
) -> Tau2DomainRun:
    seed = DOMAIN_SEEDS[domain]
    config = BenchmarkRunConfig(
        family=BenchmarkFamily.TAU2_BENCH,
        agent=coordinate.agent,
        backend=coordinate.backend,
        seed=seed,
        top_k=comparison.top_k,
        resume=False,
        use_mock_agent=comparison.use_mock_agent,
        agent_executable=comparison.agent_executable,
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
    write_run_trajectory(
        trajectory_path,
        domain=domain,
        result=result,
        fixture=fixture,
        comparison=comparison,
        env_executions=env_executions,
    )
    return Tau2DomainRun(
        domain=domain,
        result=result,
        trajectory_path=str(trajectory_path),
        env_executions=env_executions,
    )


def _resolve_cell_status(
    coordinate: Tau2MatrixCoordinate,
    *,
    include_openclaw: bool,
    use_mock_agent: bool,
) -> tuple[str, str | None]:
    if coordinate.agent is AgentKind.OPENCLAW and not include_openclaw:
        return (
            "pending_mem75",
            f"Deferred pending {OPENCLAW_PENDING_ISSUE} OpenClaw end-to-end verification.",
        )

    backend_supported, backend_reason = cell_support_rationale(
        coordinate.agent,
        coordinate.backend,
    )
    if not backend_supported:
        return "unsupported", backend_reason

    config = BenchmarkRunConfig(
        family=BenchmarkFamily.TAU2_BENCH,
        agent=coordinate.agent,
        backend=coordinate.backend,
        seed=0,
        use_mock_agent=use_mock_agent,
    )
    runner_supported, runner_reason = is_supported_coordinate(config)
    if not runner_supported:
        return "unsupported", runner_reason

    return "completed", runner_reason


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
    env_dir = root / "environment_executions"
    trajectories_dir.mkdir(parents=True, exist_ok=True)
    env_dir.mkdir(parents=True, exist_ok=True)
    trajectory_index = root / "trajectory_index.jsonl"
    if trajectory_index.exists():
        trajectory_index.unlink()

    env_cache: dict[Tau2Domain, tuple[SyntheticFixture, list[Tau2EnvironmentExecution]]] = {}
    cell_results: list[Tau2CellResult] = []

    for coordinate in tau2_matrix_coordinates():
        status, rationale = _resolve_cell_status(
            coordinate,
            include_openclaw=comparison.include_openclaw,
            use_mock_agent=comparison.use_mock_agent,
        )
        cell = Tau2CellResult(
            coordinate=coordinate,
            status=status,
            rationale=rationale,
        )

        if status == "completed":
            for domain in comparison.domains:
                try:
                    fixture, env_executions = _resolve_domain_fixture(
                        domain,
                        comparison,
                        env_cache=env_cache,
                    )
                    if env_executions and comparison.mode is Tau2ComparisonMode.REAL:
                        env_path = env_dir / f"{domain.value}-environment.json"
                        if not env_path.exists():
                            env_path.write_text(
                                json.dumps(
                                    [execution.to_dict() for execution in env_executions],
                                    indent=2,
                                    default=str,
                                ),
                                encoding="utf-8",
                            )
                    domain_run = _run_domain_cell(
                        coordinate,
                        domain,
                        comparison=comparison,
                        output_root=runs_root,
                        trajectories_dir=trajectories_dir,
                        fixture=fixture,
                        env_executions=env_executions,
                    )
                    cell.domain_results[domain] = domain_run
                    append_trajectory_index(
                        trajectory_index,
                        [
                            {
                                "run_id": domain_run.result.run_id,
                                "domain": domain.value,
                                "agent": coordinate.agent.value,
                                "backend": coordinate.backend.value,
                                "trajectory_path": domain_run.trajectory_path,
                                "mode": comparison.mode.value,
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
