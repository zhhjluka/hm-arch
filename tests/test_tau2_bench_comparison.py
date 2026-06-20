"""Tests for tau2-bench agent-experience comparison (HM-76 / MEM-76)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from benchmarks.cross_agent.tau2.agent_cli import (
    classify_cli_failure,
    is_harness_executable,
    production_cli_status,
)
from benchmarks.cross_agent.tau2.agent_loop import (
    HARNESS_AGENT_LABEL,
    _build_tau2_prompt,
    run_task_agent_loop,
)
from benchmarks.cross_agent.tau2.availability import tau2_is_available
from benchmarks.cross_agent.tau2.config import (
    COMPARISON_AGENTS,
    COMPARISON_BACKENDS,
    Tau2ComparisonConfig,
    Tau2ComparisonMode,
    Tau2Domain,
    tau2_matrix_coordinates,
)
from benchmarks.cross_agent.tau2.environment_runner import (
    GOLD_REPLAY_HARNESS_LABEL,
    execute_domain_tasks,
)
from benchmarks.cross_agent.tau2.fixtures import get_tau2_domain_fixture
from benchmarks.cross_agent.tau2.loader import load_tau2_tasks
from benchmarks.cross_agent.tau2.runner import run_tau2_comparison
from benchmarks.cross_agent.tau2.smoke_fixtures import SMOKE_FIXTURE_LABEL, retail_smoke_fixture
from benchmarks.cross_agent.types import AgentKind, BenchmarkRunConfig, MemoryBackendKind
from benchmarks.cross_agent.agents.workspace import AgentWorkspace

pytestmark = pytest.mark.filterwarnings("ignore::DeprecationWarning")


def _fake_tau2_cli_executable() -> str:
    return str(Path(__file__).resolve().parent / "fixtures" / "fake_tau2_agent_cli.py")


def _smoke_config(tmp_path: Path) -> Tau2ComparisonConfig:
    return Tau2ComparisonConfig(
        output_root=str(tmp_path),
        mode=Tau2ComparisonMode.SMOKE,
        use_mock_agent=True,
    )


def _harness_config(tmp_path: Path) -> Tau2ComparisonConfig:
    return Tau2ComparisonConfig(
        output_root=str(tmp_path),
        mode=Tau2ComparisonMode.HARNESS,
        use_harness_agent=True,
        agent_executable=_fake_tau2_cli_executable(),
        agent_model="fake-tau2-agent-cli",
        agent_provider="hm-arch-test-fixture",
        user_mode="scripted",
        num_tasks=1,
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
    assert (tmp_path / "benchmark_table.json").is_file()
    assert (tmp_path / "provenance.json").is_file()
    assert len(report.rows) == len(tau2_matrix_coordinates())
    assert report.benchmark_rows == []


def test_openclaw_cells_use_production_cli_status(tmp_path: Path) -> None:
    report = run_tau2_comparison(
        Tau2ComparisonConfig(
            output_root=str(tmp_path),
            mode=Tau2ComparisonMode.REAL,
            user_mode="scripted",
            num_tasks=1,
        )
    )
    openclaw_rows = [row for row in report.rows if row.agent == AgentKind.OPENCLAW.value]
    assert len(openclaw_rows) == len(COMPARISON_BACKENDS)
    assert all(
        row.status in {"unavailable", "failed", "completed", "unsupported"}
        for row in openclaw_rows
    )
    assert all(row.status != "pending_mem75" for row in openclaw_rows)


@pytest.mark.skipif(not tau2_is_available(), reason="tau2-bench not installed")
def test_real_tau2_tasks_load_for_retail_and_airline() -> None:
    retail = load_tau2_tasks(Tau2Domain.RETAIL, num_tasks=3)
    airline = load_tau2_tasks(Tau2Domain.AIRLINE, num_tasks=3)
    assert len(retail) == 3
    assert len(airline) == 3
    assert retail[0].evaluation_criteria.actions


@pytest.mark.skipif(not tau2_is_available(), reason="tau2-bench not installed")
def test_gold_replay_harness_is_labeled() -> None:
    tasks = load_tau2_tasks(Tau2Domain.RETAIL, num_tasks=1)
    executions = execute_domain_tasks(Tau2Domain.RETAIL, tasks)
    assert executions[0].evaluation.get("harness_label") == GOLD_REPLAY_HARNESS_LABEL


@pytest.mark.skipif(not tau2_is_available(), reason="tau2-bench not installed")
def test_agent_loop_harness_drives_environment_with_cli(tmp_path: Path) -> None:
    tasks = load_tau2_tasks(Tau2Domain.RETAIL, num_tasks=1)
    config = BenchmarkRunConfig(
        family="tau2_bench",
        agent=AgentKind.CODEX,
        backend=MemoryBackendKind.NO_MEMORY,
        seed=0,
    )
    workspace = AgentWorkspace.create(
        AgentKind.CODEX,
        run_id="tau2-harness-test",
        parent=tmp_path,
    )
    execution = run_task_agent_loop(
        Tau2Domain.RETAIL,
        tasks[0],
        agent=AgentKind.CODEX,
        config=config,
        workspace=workspace,
        storage_dir=tmp_path / "storage",
        executable=_fake_tau2_cli_executable(),
        use_harness_agent=True,
        user_mode="scripted",
        max_steps=30,
    )
    workspace.cleanup()
    assert execution.harness_label == HARNESS_AGENT_LABEL
    assert execution.steps
    assert execution.steps[0].argv
    assert "tau2-step" in " ".join(execution.steps[0].argv)
    assert execution.simulation_messages
    assert execution.reward is not None


@pytest.mark.skipif(not tau2_is_available(), reason="tau2-bench not installed")
def test_run_harness_comparison_writes_agent_trajectories(tmp_path: Path) -> None:
    report = run_tau2_comparison(_harness_config(tmp_path))
    assert report.mode == "harness"
    codex_hm = next(
        row
        for row in report.rows
        if row.agent == AgentKind.CODEX.value and row.backend == MemoryBackendKind.HM_ARCH.value
    )
    assert codex_hm.status == "completed"
    assert codex_hm.excluded_from_benchmark_table is True
    assert codex_hm.retail_trajectory_path
    trajectory = json.loads(
        Path(codex_hm.retail_trajectory_path).read_text(encoding="utf-8").splitlines()[0]
    )
    assert trajectory["comparison_mode"] == "harness"
    assert trajectory["steps"]
    assert trajectory["simulation_messages"]
    assert report.benchmark_rows == []


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
    fixture = get_tau2_domain_fixture(Tau2Domain.RETAIL, mode=Tau2ComparisonMode.HARNESS, num_tasks=2)
    assert all("tau2_task_id" in item.metadata for item in fixture.ingest_items)


def test_real_mode_rejects_harness_executable(tmp_path: Path) -> None:
    config = Tau2ComparisonConfig(
        output_root=str(tmp_path),
        mode=Tau2ComparisonMode.REAL,
        user_mode="scripted",
        agent_executable=_fake_tau2_cli_executable(),
    )
    report = run_tau2_comparison(config)
    codex = next(row for row in report.rows if row.agent == AgentKind.CODEX.value)
    assert codex.status == "failed"
    assert "agent-executable" in (codex.rationale or "").lower()
    assert report.benchmark_rows == []


def test_real_mode_requires_user_llm(tmp_path: Path) -> None:
    config = Tau2ComparisonConfig(
        output_root=str(tmp_path),
        mode=Tau2ComparisonMode.REAL,
        user_mode="llm",
        user_llm=None,
    )
    report = run_tau2_comparison(config)
    codex = next(row for row in report.rows if row.agent == AgentKind.CODEX.value)
    assert codex.status == "failed"
    assert "user-llm" in (codex.rationale or "").lower()
    assert report.benchmark_rows == []


def test_real_mode_marks_missing_cli_unavailable(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("HM_ARCH_BENCH_CODEX_EXECUTABLE", raising=False)
    monkeypatch.delenv("HM_ARCH_BENCH_CLAUDE_CODE_EXECUTABLE", raising=False)
    config = Tau2ComparisonConfig(
        output_root=str(tmp_path),
        mode=Tau2ComparisonMode.REAL,
        user_mode="scripted",
        num_tasks=1,
    )
    report = run_tau2_comparison(config)
    codex = next(
        row
        for row in report.rows
        if row.agent == AgentKind.CODEX.value and row.backend == MemoryBackendKind.NO_MEMORY.value
    )
    assert codex.status == "unavailable"
    assert report.benchmark_rows == []


def test_scripted_real_pilot_is_excluded_from_benchmark_table(tmp_path: Path) -> None:
    config = Tau2ComparisonConfig(
        output_root=str(tmp_path),
        mode=Tau2ComparisonMode.REAL,
        user_mode="scripted",
        num_tasks=1,
    )
    report = run_tau2_comparison(config)
    assert report.provenance.get("user_simulator_label") == "scripted_user_pilot"
    assert report.benchmark_rows == []


def test_is_harness_executable_detects_fake_cli() -> None:
    assert is_harness_executable(_fake_tau2_cli_executable())


def test_production_cli_status_preserves_real_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = str(Path(__file__).resolve().parent / "fixtures" / "fake_agent_cli.py")
    monkeypatch.setenv("HM_ARCH_BENCH_CODEX_EXECUTABLE", fake)
    status, reason = production_cli_status(AgentKind.CODEX)
    assert status == "ready"
    assert "production CLI resolved" in reason


def test_production_cli_status_marks_benchmark_double_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = str(Path(__file__).resolve().parent / "fixtures" / "fake_tau2_agent_cli.py")
    monkeypatch.setenv("HM_ARCH_BENCH_CODEX_EXECUTABLE", fake)
    status, reason = production_cli_status(AgentKind.CODEX)
    assert status == "failed"
    assert "harness double" in reason


@pytest.mark.skipif(not tau2_is_available(), reason="tau2-bench not installed")
def test_build_tau2_prompt_includes_tool_parameter_schemas() -> None:
    from tau2.runner.build import build_environment

    tasks = load_tau2_tasks(Tau2Domain.RETAIL, num_tasks=1)
    environment = build_environment("retail", solo_mode=False)
    tools = list(environment.get_tools())
    prompt = _build_tau2_prompt(
        domain=Tau2Domain.RETAIL,
        task=tasks[0],
        observation="user: hello",
        policy=environment.get_policy(),
        tools=tools,
        memory_context="",
        step_index=0,
    )
    assert '"properties"' in prompt or '"type":"object"' in prompt.replace(" ", "")


def _fake_agent_cli_executable() -> str:
    return str(Path(__file__).resolve().parent / "fixtures" / "fake_agent_cli.py")


@pytest.mark.skipif(not tau2_is_available(), reason="tau2-bench not installed")
def test_non_gold_action_fails_without_harness(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HM_ARCH_BENCH_CODEX_EXECUTABLE", _fake_agent_cli_executable())
    tasks = load_tau2_tasks(Tau2Domain.RETAIL, num_tasks=1)
    config = BenchmarkRunConfig(
        family="tau2_bench",
        agent=AgentKind.CODEX,
        backend=MemoryBackendKind.NO_MEMORY,
        seed=0,
    )
    workspace = AgentWorkspace.create(
        AgentKind.CODEX,
        run_id="tau2-non-gold",
        parent=tmp_path,
    )
    execution = run_task_agent_loop(
        Tau2Domain.RETAIL,
        tasks[0],
        agent=AgentKind.CODEX,
        config=config,
        workspace=workspace,
        storage_dir=tmp_path / "storage",
        executable=None,
        use_harness_agent=False,
        user_mode="scripted",
        max_steps=1,
    )
    workspace.cleanup()
    assert execution.harness_label is None
    assert execution.error or any(step.error for step in execution.steps) or not execution.task_success


def test_real_mode_cli_user_is_benchmark_eligible_label(tmp_path: Path) -> None:
    config = Tau2ComparisonConfig(
        output_root=str(tmp_path),
        mode=Tau2ComparisonMode.REAL,
        user_mode="cli",
    )
    assert config.user_simulator_label() == "cli_user_simulator"


def test_classify_cli_failure_detects_auth_errors() -> None:
    assert classify_cli_failure("Error: not logged in. Run codex login") == "agent_cli_auth_failure"