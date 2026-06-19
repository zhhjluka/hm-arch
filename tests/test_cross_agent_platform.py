"""Focused platform tests for CLI parsers and benchmark storage layout."""

from __future__ import annotations

import json
import stat
import sys
from pathlib import Path

import pytest

from benchmarks.cross_agent.agents.cli_parsers import (
    parse_claude_json_output,
    parse_codex_exec_jsonl,
    parse_openclaw_agent_json,
)
from benchmarks.cross_agent.agents.cli_runner import (
    AgentRunnerContext,
    ClaudeCodeCliAgentRunner,
    CodexCliAgentRunner,
    HermesCliAgentRunner,
    OpenClawCliAgentRunner,
)
from benchmarks.cross_agent.agents.hm_arch_bench import (
    agent_prompt_context,
    agent_uses_hook_recall,
)
from benchmarks.cross_agent.agents.workspace import AgentWorkspace
from benchmarks.cross_agent.backends.hm_arch_paths import hm_arch_db_path
from benchmarks.cross_agent.fixtures.synthetic import locomo_fixture
from benchmarks.cross_agent.runner import CrossAgentBenchmarkHarness
from benchmarks.cross_agent.types import (
    AgentKind,
    BenchmarkFamily,
    BenchmarkRunConfig,
    MemoryBackendKind,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
FIXTURES = REPO_ROOT / "tests" / "fixtures" / "cli_output"
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


def test_parse_codex_exec_jsonl_fixture() -> None:
    stdout = (FIXTURES / "codex_exec_success.jsonl").read_text(encoding="utf-8")
    parsed = parse_codex_exec_jsonl(stdout, prompt_text="ignored")
    assert parsed["answer"] == "Seattle"
    assert parsed["input_tokens"] == 128
    assert parsed["output_tokens"] == 4
    assert parsed["input_token_source"] == "exact"
    assert parsed["output_token_source"] == "exact"


def test_parse_claude_json_fixture() -> None:
    stdout = (FIXTURES / "claude_json_success.json").read_text(encoding="utf-8")
    parsed = parse_claude_json_output(stdout, prompt_text="ignored")
    assert parsed["answer"] == "Seattle"
    assert parsed["input_tokens"] == 96
    assert parsed["output_tokens"] == 3
    assert parsed["input_token_source"] == "exact"


def test_parse_openclaw_agent_json_fixture() -> None:
    stdout = (FIXTURES / "openclaw_agent_success.json").read_text(encoding="utf-8")
    parsed = parse_openclaw_agent_json(stdout, prompt_text="ignored")
    assert parsed["answer"] == "Seattle"
    assert parsed["input_tokens"] == 110
    assert parsed["output_tokens"] == 2
    assert parsed["output_token_source"] == "exact"


@pytest.mark.parametrize(
    ("runner_cls", "agent", "expected_runner"),
    [
        (CodexCliAgentRunner, AgentKind.CODEX, "codex-exec-jsonl"),
        (ClaudeCodeCliAgentRunner, AgentKind.CLAUDE_CODE, "claude-json"),
        (HermesCliAgentRunner, AgentKind.HERMES, "hermes-oneshot"),
        (OpenClawCliAgentRunner, AgentKind.OPENCLAW, "openclaw-agent-json"),
    ],
)
def test_real_cli_paths_use_parser_shapes(
    tmp_path: Path,
    fake_executable: str,
    runner_cls: type,
    agent: AgentKind,
    expected_runner: str,
) -> None:
    workspace = AgentWorkspace.create(agent, parent=tmp_path)
    storage_dir = tmp_path / "storage"
    storage_dir.mkdir()
    config = BenchmarkRunConfig(
        family=BenchmarkFamily.LOCOMO,
        agent=runner_cls.agent,
        backend=MemoryBackendKind.NO_MEMORY,
        use_mock_agent=False,
        agent_executable=fake_executable,
    )
    runner = runner_cls(
        AgentRunnerContext(
            workspace=workspace,
            config=config,
            storage_dir=storage_dir,
            executable=fake_executable,
        )
    )
    try:
        runner.open()
        outcome = runner.answer(
            locomo_fixture().queries[0],
            recalled_context="Caroline moved to Seattle.",
            seed=0,
        )
    finally:
        runner.close()
        workspace.cleanup()

    assert outcome.failure_count == 0
    assert outcome.metadata.get("cli_runner") == expected_runner
    if expected_runner in {"codex-exec-jsonl", "claude-json", "openclaw-agent-json"}:
        assert outcome.input_token_source == "exact"
        assert outcome.output_token_source == "exact"


def test_storage_survives_workspace_cleanup_and_resume(
    tmp_path: Path,
    fake_executable: str,
) -> None:
    config = BenchmarkRunConfig(
        family=BenchmarkFamily.TAU2_BENCH,
        agent=AgentKind.CODEX,
        backend=MemoryBackendKind.HM_ARCH,
        seed=0,
        resume=True,
        use_mock_agent=False,
        agent_executable=fake_executable,
    )
    harness = CrossAgentBenchmarkHarness(output_root=tmp_path)
    first = harness.run(config)
    run_dir = tmp_path / first.run_id
    storage = run_dir / "storage"
    workspace = run_dir / "agent_workspace"
    assert storage.is_dir()
    assert (storage / "checkpoint.json").is_file()
    assert hm_arch_db_path(storage).is_file()
    assert not workspace.exists()

    second = harness.run(config)
    assert second.run_id == first.run_id
    assert len(second.queries) == len(first.queries)
    assert hm_arch_db_path(storage).is_file()


def test_hook_recall_skips_prompt_injection_for_hm_arch_cli() -> None:
    config = BenchmarkRunConfig(
        family=BenchmarkFamily.LOCOMO,
        agent=AgentKind.CODEX,
        backend=MemoryBackendKind.HM_ARCH,
        use_mock_agent=False,
    )
    assert agent_uses_hook_recall(config) is True
    assert agent_prompt_context(config, "injected context") == ""

    mock_config = BenchmarkRunConfig(
        family=BenchmarkFamily.LOCOMO,
        agent=AgentKind.CODEX,
        backend=MemoryBackendKind.HM_ARCH,
        use_mock_agent=True,
    )
    assert agent_uses_hook_recall(mock_config) is False
    assert agent_prompt_context(mock_config, "injected context") == "injected context"


def test_hm_arch_cli_run_records_token_sources(
    tmp_path: Path,
    fake_executable: str,
) -> None:
    config = BenchmarkRunConfig(
        family=BenchmarkFamily.LOCOMO,
        agent=AgentKind.CODEX,
        backend=MemoryBackendKind.HM_ARCH,
        seed=0,
        resume=False,
        use_mock_agent=False,
        agent_executable=fake_executable,
    )
    result = CrossAgentBenchmarkHarness(output_root=tmp_path).run(config)
    assert result.aggregates.total_failure_count == 0
    assert all(q.input_token_source == "exact" for q in result.queries)
    summary = json.loads((tmp_path / result.run_id / "summary.json").read_text())
    assert summary["agent_metadata"]["storage_dir"].endswith("/storage")
