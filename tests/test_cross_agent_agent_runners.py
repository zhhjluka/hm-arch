"""Production agent runner smoke tests with fake executables (HM-73 / MEM-71)."""

from __future__ import annotations

import json
import os
import stat
import sys
from pathlib import Path

import pytest

from benchmarks.cross_agent.agents.registry import create_agent_runner, is_supported_coordinate
from benchmarks.cross_agent.agents.workspace import AgentWorkspace
from benchmarks.cross_agent.compatibility import (
    CellImplementation,
    compatibility_snapshot,
    lookup_matrix_cell,
    smoke_matrix_configs,
)
from benchmarks.cross_agent.fixtures.synthetic import get_synthetic_fixture, locomo_fixture
from benchmarks.cross_agent.runner import CrossAgentBenchmarkHarness
from benchmarks.cross_agent.types import (
    AgentKind,
    BenchmarkFamily,
    BenchmarkRunConfig,
    MemoryBackendKind,
)


REPO_ROOT = Path(__file__).resolve().parents[1]
FAKE_CLI = REPO_ROOT / "tests" / "fixtures" / "fake_agent_cli.py"


def _write_fake_executable(path: Path) -> str:
    script = f"""#!/bin/sh
exec {sys.executable} {FAKE_CLI} "$@"
"""
    path.write_text(script, encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IEXEC)
    return str(path)


@pytest.fixture
def fake_executable(tmp_path: Path) -> str:
    return _write_fake_executable(tmp_path / "fake-agent-cli")


@pytest.mark.parametrize("agent", list(AgentKind))
def test_smoke_fixture_runs_with_fake_cli(
    tmp_path: Path,
    fake_executable: str,
    agent: AgentKind,
) -> None:
    for backend in (MemoryBackendKind.NO_MEMORY, MemoryBackendKind.HM_ARCH):
        config = BenchmarkRunConfig(
            family=BenchmarkFamily.LOCOMO,
            agent=agent,
            backend=backend,
            seed=0,
            resume=False,
            use_mock_agent=False,
            agent_executable=fake_executable,
            agent_timeout_s=10.0,
        )
        result = CrossAgentBenchmarkHarness(output_root=tmp_path / agent.value).run(config)
        assert result.agent_metadata.get("supported") is True, result.agent_metadata
        assert result.aggregates.total_failure_count == 0
        assert result.aggregates.query_count == len(get_synthetic_fixture(BenchmarkFamily.LOCOMO).queries)
        assert result.compatibility


@pytest.mark.parametrize("agent", list(AgentKind))
def test_native_and_external_modes_are_distinguishable(
    fake_executable: str,
    agent: AgentKind,
    tmp_path: Path,
) -> None:
    labels: set[str] = set()
    for backend in (MemoryBackendKind.NO_MEMORY, MemoryBackendKind.HM_ARCH):
        config = BenchmarkRunConfig(
            family=BenchmarkFamily.LOCOMO,
            agent=agent,
            backend=backend,
            seed=0,
            resume=False,
            use_mock_agent=False,
            agent_executable=fake_executable,
        )
        result = CrossAgentBenchmarkHarness(output_root=tmp_path / f"{agent.value}-{backend.value}").run(
            config
        )
        labels.add(config.backend.value)
        assert result.config.backend is backend
        summary = json.loads(
            (tmp_path / f"{agent.value}-{backend.value}" / result.run_id / "summary.json").read_text()
        )
        assert summary["config"]["backend"] == backend.value
    assert labels == {"no_memory", "hm_arch"}


def test_temporary_homes_do_not_touch_real_agent_configuration(
    tmp_path: Path,
    fake_executable: str,
) -> None:
    real_home = tmp_path / "real_codex_home"
    real_home.mkdir()
    sentinel = real_home / "sentinel.txt"
    sentinel.write_text("unchanged", encoding="utf-8")

    previous = os.environ.get("CODEX_HOME")
    os.environ["CODEX_HOME"] = str(real_home)
    try:
        config = BenchmarkRunConfig(
            family=BenchmarkFamily.LOCOMO,
            agent=AgentKind.CODEX,
            backend=MemoryBackendKind.NO_MEMORY,
            seed=0,
            resume=False,
            use_mock_agent=False,
            agent_executable=fake_executable,
        )
        result = CrossAgentBenchmarkHarness(output_root=tmp_path / "bench").run(config)
        assert result.aggregates.total_failure_count == 0
        assert str(real_home) not in json.dumps(result.agent_metadata)
    finally:
        if previous is None:
            os.environ.pop("CODEX_HOME", None)
        else:
            os.environ["CODEX_HOME"] = previous

    assert sentinel.read_text(encoding="utf-8") == "unchanged"


def test_unsupported_cells_remain_visible_in_report(tmp_path: Path) -> None:
    config = BenchmarkRunConfig(
        family=BenchmarkFamily.LOCOMO,
        agent=AgentKind.HERMES,
        backend=MemoryBackendKind.MEM0,
        seed=0,
        resume=False,
        use_mock_agent=False,
    )
    cell = lookup_matrix_cell(config.agent, config.backend)
    assert cell.implementation is CellImplementation.UNSUPPORTED
    supported, _ = is_supported_coordinate(config)
    assert supported is False
    result = CrossAgentBenchmarkHarness(output_root=tmp_path).run(config)
    assert result.agent_metadata.get("status") == "unsupported"
    assert result.queries == []
    assert "mem0" in result.agent_metadata.get("error", "").lower() or "Mem0" in result.agent_metadata.get(
        "error", ""
    )


def test_compatibility_matrix_is_explicit() -> None:
    matrix = compatibility_snapshot()
    assert matrix["codex|hm_arch"] == CellImplementation.REAL.value
    assert matrix["codex|native_memory"] == CellImplementation.UNSUPPORTED.value
    assert matrix["hermes|mem0"] == CellImplementation.UNSUPPORTED.value
    assert any(key.startswith("openclaw|") for key in matrix)


def test_cli_runner_captures_exit_status_and_stderr(tmp_path: Path) -> None:
    bad_cli = tmp_path / "bad-cli"
    bad_cli.write_text(
        "#!/bin/sh\n"
        "echo 'boom' 1>&2\n"
        "exit 7\n",
        encoding="utf-8",
    )
    bad_cli.chmod(bad_cli.stat().st_mode | stat.S_IEXEC)

    workspace = AgentWorkspace.create(AgentKind.CODEX, parent=tmp_path)
    storage_dir = tmp_path / "storage"
    storage_dir.mkdir()
    config = BenchmarkRunConfig(
        family=BenchmarkFamily.LOCOMO,
        agent=AgentKind.CODEX,
        backend=MemoryBackendKind.NO_MEMORY,
        use_mock_agent=False,
        agent_executable=str(bad_cli),
    )
    context_config = config
    from benchmarks.cross_agent.agents.cli_runner import AgentRunnerContext, CodexCliAgentRunner

    runner = CodexCliAgentRunner(
        AgentRunnerContext(
            workspace=workspace,
            config=context_config,
            storage_dir=storage_dir,
            executable=str(bad_cli),
        )
    )
    try:
        runner.open()
        outcome = runner.answer(
            locomo_fixture().queries[0],
            recalled_context="context",
            seed=0,
        )
    finally:
        runner.close()
        workspace.cleanup()

    assert outcome.failure_count == 1
    assert outcome.metadata.get("exit_code") == 7
    assert "boom" in outcome.metadata.get("stderr", "")


def test_smoke_matrix_declares_real_cells() -> None:
    configs = smoke_matrix_configs()
    assert len(configs) == len(AgentKind) * 2
    for agent, backend in configs:
        cell = lookup_matrix_cell(agent, backend)
        assert cell.implementation is CellImplementation.REAL


def test_mock_runner_is_explicit_test_double() -> None:
    runner = create_agent_runner(AgentKind.CODEX)
    assert runner.kind == "mock-synthetic"


def test_smoke_dataset_id_is_stable() -> None:
    from benchmarks.cross_agent.fixtures.smoke import SMOKE_DATASET_ID

    assert SMOKE_DATASET_ID == "cross-agent-smoke-v1"
