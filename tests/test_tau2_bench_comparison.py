"""Tests for tau2-bench agent-experience comparison (HM-76 / MEM-76)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from benchmarks.cross_agent.tau2.availability import tau2_is_available
from benchmarks.cross_agent.tau2.config import (
    COMPARISON_AGENTS,
    COMPARISON_BACKENDS,
    Tau2ComparisonConfig,
    Tau2ComparisonMode,
    Tau2Domain,
    tau2_matrix_coordinates,
)
from benchmarks.cross_agent.tau2.environment_runner import execute_domain_tasks
from benchmarks.cross_agent.tau2.fixtures import get_tau2_domain_fixture
from benchmarks.cross_agent.tau2.loader import load_tau2_tasks
from benchmarks.cross_agent.tau2.runner import run_tau2_comparison
from benchmarks.cross_agent.tau2.smoke_fixtures import SMOKE_FIXTURE_LABEL, retail_smoke_fixture
from benchmarks.cross_agent.types import AgentKind, MemoryBackendKind

pytestmark = pytest.mark.filterwarnings("ignore::DeprecationWarning")


def _fake_cli_executable() -> str:
    return str(Path(__file__).resolve().parent / "fixtures" / "fake_agent_cli.py")


def _smoke_config(tmp_path: Path) -> Tau2ComparisonConfig:
    return Tau2ComparisonConfig(
        output_root=str(tmp_path),
        mode=Tau2ComparisonMode.SMOKE,
        use_mock_agent=True,
    )


def _real_config(tmp_path: Path) -> Tau2ComparisonConfig:
    return Tau2ComparisonConfig(
        output_root=str(tmp_path),
        mode=Tau2ComparisonMode.REAL,
        use_mock_agent=False,
        agent_executable=_fake_cli_executable(),
        agent_model="fake-agent-cli",
        agent_provider="hm-arch-test-fixture",
    )


def test_smoke_domain_fixtures_are_labeled() -> None:
    retail = retail_smoke_fixture()
    assert all(
        item.metadata.get("fixture_source") == SMOKE_FIXTURE_LABEL
        for item in retail.ingest_items
    )


def test_tau2_matrix_has_full_agent_backend_grid() -> None:
    coordinates = tau2_matrix_coordinates()
    assert len(coordinates) == len(COMPARISON_AGENTS) * len(COMPARISON_BACKENDS)
    keys = {(coord.agent, coord.backend) for coord in coordinates}
    for agent in COMPARISON_AGENTS:
        for backend in COMPARISON_BACKENDS:
            assert (agent, backend) in keys


def test_run_smoke_comparison_writes_artifacts(tmp_path: Path) -> None:
    report = run_tau2_comparison(_smoke_config(tmp_path))
    assert report.issue == "MEM-76"
    assert report.mode == "smoke"
    assert (tmp_path / "summary_table.json").is_file()
    assert (tmp_path / "provenance.json").is_file()
    assert len(report.rows) == len(tau2_matrix_coordinates())


def test_openclaw_cells_are_pending_mem75(tmp_path: Path) -> None:
    report = run_tau2_comparison(_smoke_config(tmp_path))
    openclaw_rows = [row for row in report.rows if row.agent == AgentKind.OPENCLAW.value]
    assert len(openclaw_rows) == len(COMPARISON_BACKENDS)
    assert all(row.status == "pending_mem75" for row in openclaw_rows)


@pytest.mark.skipif(not tau2_is_available(), reason="tau2-bench not installed")
def test_real_tau2_tasks_load_for_retail_and_airline() -> None:
    retail = load_tau2_tasks(Tau2Domain.RETAIL, num_tasks=3)
    airline = load_tau2_tasks(Tau2Domain.AIRLINE, num_tasks=3)
    assert len(retail) == 3
    assert len(airline) == 3
    assert retail[0].evaluation_criteria.actions


@pytest.mark.skipif(not tau2_is_available(), reason="tau2-bench not installed")
def test_real_environment_executes_tau2_tools() -> None:
    tasks = load_tau2_tasks(Tau2Domain.RETAIL, num_tasks=1)
    executions = execute_domain_tasks(Tau2Domain.RETAIL, tasks)
    assert len(executions) == 1
    assert executions[0].action_steps
    assert executions[0].reward is not None


@pytest.mark.skipif(not tau2_is_available(), reason="tau2-bench not installed")
def test_run_real_comparison_with_cli_fixture(tmp_path: Path) -> None:
    report = run_tau2_comparison(_real_config(tmp_path))
    assert report.mode == "real"
    codex_hm = next(
        row
        for row in report.rows
        if row.agent == AgentKind.CODEX.value and row.backend == MemoryBackendKind.HM_ARCH.value
    )
    assert codex_hm.status == "completed"
    assert codex_hm.retail_trajectory_path
    assert (tmp_path / "environment_executions" / "retail-environment.json").is_file()
    trajectory = json.loads(
        Path(codex_hm.retail_trajectory_path).read_text(encoding="utf-8").splitlines()[0]
    )
    assert trajectory["agent_metadata"]["comparison_mode"] == "real"
    assert trajectory["environment_executions"]


@pytest.mark.parametrize(
    ("agent", "backend"),
    [
        (AgentKind.CODEX, MemoryBackendKind.NATIVE_MEMORY),
        (AgentKind.CODEX, MemoryBackendKind.MEM0),
        (AgentKind.HERMES, MemoryBackendKind.OPENVIKING),
        (AgentKind.CLAUDE_CODE, MemoryBackendKind.OPENVIKING),
    ],
)
def test_unsupported_cells_are_visible(
    tmp_path: Path,
    agent: AgentKind,
    backend: MemoryBackendKind,
) -> None:
    report = run_tau2_comparison(_smoke_config(tmp_path / f"{agent.value}-{backend.value}"))
    row = next(
        row for row in report.rows if row.agent == agent.value and row.backend == backend.value
    )
    assert row.status == "unsupported"
    assert row.rationale


def test_smoke_hm_arch_beats_no_memory_on_retail(tmp_path: Path) -> None:
    report = run_tau2_comparison(_smoke_config(tmp_path))
    hm = next(
        row
        for row in report.rows
        if row.agent == AgentKind.CODEX.value and row.backend == MemoryBackendKind.HM_ARCH.value
    )
    none = next(
        row
        for row in report.rows
        if row.agent == AgentKind.CODEX.value and row.backend == MemoryBackendKind.NO_MEMORY.value
    )
    assert hm.retail_mean_accuracy is not None
    assert none.retail_mean_accuracy is not None
    assert hm.retail_mean_accuracy >= none.retail_mean_accuracy


def test_real_fixture_uses_tau2_task_ids() -> None:
    if not tau2_is_available():
        pytest.skip("tau2-bench not installed")
    fixture = get_tau2_domain_fixture(Tau2Domain.RETAIL, mode=Tau2ComparisonMode.REAL, num_tasks=2)
    assert all("tau2_task_id" in item.metadata for item in fixture.ingest_items)
    assert all(query.metadata.get("fixture_source") == "tau2_bench_v1.0.0" for query in fixture.queries)
