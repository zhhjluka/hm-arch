"""Focused platform tests for CLI parsers and benchmark storage layout."""

from __future__ import annotations

import json
import os
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
    hm_arch_cli_env,
    openclaw_benchmark_config_path,
)
from benchmarks.cross_agent.agents.workspace import AgentWorkspace
from benchmarks.cross_agent.backends.hm_arch_paths import hm_arch_db_path, hm_arch_db_path_str
from benchmarks.cross_agent.fixtures.synthetic import locomo_fixture
from benchmarks.cross_agent.runner import CrossAgentBenchmarkHarness
from benchmarks.cross_agent.types import (
    AgentKind,
    BenchmarkFamily,
    BenchmarkRunConfig,
    MemoryBackendKind,
)

from hm_arch.integrations.openclaw.config import HM_ARCH_PLUGIN_ID, load_openclaw_config

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


@pytest.mark.parametrize(
    ("agent", "credential_paths"),
    [
        (AgentKind.CODEX, (".codex/auth.json",)),
        (AgentKind.HERMES, (".hermes/.env", ".hermes/auth.json")),
    ],
)
def test_agent_workspace_stages_only_allowlisted_credentials(
    tmp_path: Path,
    agent: AgentKind,
    credential_paths: tuple[str, ...],
) -> None:
    source_home = tmp_path / "source-home"
    for relative_path in credential_paths:
        source = source_home / relative_path
        source.parent.mkdir(parents=True, exist_ok=True)
        source.write_text("credential", encoding="utf-8")
    memory = source_home / f".{agent.value}" / "memories" / "MEMORY.md"
    memory.parent.mkdir(parents=True, exist_ok=True)
    memory.write_text("must not leak", encoding="utf-8")

    workspace = AgentWorkspace.create(
        agent,
        parent=tmp_path / "run",
        credential_source_home=source_home,
    )

    expected_names = {Path(path).name for path in credential_paths}
    assert expected_names.issubset({path.name for path in workspace.agent_home.iterdir()})
    assert not (workspace.agent_home / "memories").exists()


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
    assert agent_prompt_context(config, "injected context", hook_managed=True) == ""

    mock_config = BenchmarkRunConfig(
        family=BenchmarkFamily.LOCOMO,
        agent=AgentKind.CODEX,
        backend=MemoryBackendKind.HM_ARCH,
        use_mock_agent=True,
    )
    assert agent_uses_hook_recall(mock_config) is False
    assert (
        agent_prompt_context(mock_config, "injected context", hook_managed=False)
        == "injected context"
    )


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
    assert all(q.agent_managed is True for q in result.queries)
    assert all(q.retrieval_hit_rate is None for q in result.queries)
    assert all(q.recall_time_ms == 0.0 for q in result.queries)
    summary = json.loads((tmp_path / result.run_id / "summary.json").read_text())
    assert summary["agent_metadata"]["storage_dir"].endswith("/storage")


def test_parse_claude_malformed_json_raises() -> None:
    with pytest.raises((json.JSONDecodeError, ValueError)):
        parse_claude_json_output("not-json", prompt_text="ignored")


def test_parse_openclaw_malformed_json_raises() -> None:
    with pytest.raises((json.JSONDecodeError, ValueError)):
        parse_openclaw_agent_json("{broken", prompt_text="ignored")


@pytest.mark.parametrize(
    ("runner_cls", "bad_stdout", "help_script"),
    [
        (
            ClaudeCodeCliAgentRunner,
            "not valid json",
            '#!/bin/sh\nif [ "$1" = "--help" ]; then echo "--output-format json"; exit 0; fi\nprintf "%s" "not valid json"\n',
        ),
        (
            OpenClawCliAgentRunner,
            "not valid json",
            '#!/bin/sh\nif [ "$1" = "agent" ] && [ "$2" = "--help" ]; then echo "--message"; exit 0; fi\nprintf "%s" "not valid json"\n',
        ),
    ],
)
def test_malformed_cli_json_is_query_failure(
    tmp_path: Path,
    runner_cls: type,
    bad_stdout: str,
    help_script: str,
) -> None:
    bad_cli = tmp_path / f"bad-json-cli-{runner_cls.agent.value}"
    bad_cli.write_text(help_script, encoding="utf-8")
    bad_cli.chmod(bad_cli.stat().st_mode | stat.S_IEXEC)

    workspace = AgentWorkspace.create(runner_cls.agent, parent=tmp_path)
    storage_dir = tmp_path / "storage"
    storage_dir.mkdir()
    config = BenchmarkRunConfig(
        family=BenchmarkFamily.LOCOMO,
        agent=runner_cls.agent,
        backend=MemoryBackendKind.NO_MEMORY,
        use_mock_agent=False,
        agent_executable=str(bad_cli),
    )
    runner = runner_cls(
        AgentRunnerContext(
            workspace=workspace,
            config=config,
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
    assert outcome.error


def _write_openclaw_env_probe(path: Path, *, capture_path: Path) -> str:
    script = f"""#!/bin/sh
if [ "$1" = "agent" ] && [ "$2" = "--help" ]; then
  echo "--message"
  exit 0
fi
{{
  echo "OPENCLAW_STATE_DIR=${{OPENCLAW_STATE_DIR:-}}"
  echo "OPENCLAW_CONFIG_PATH=${{OPENCLAW_CONFIG_PATH:-}}"
  echo "HM_ARCH_DB_PATH=${{HM_ARCH_DB_PATH:-}}"
}} > "{capture_path}"
exec {sys.executable} {FAKE_CLI} "$@"
"""
    path.write_text(script, encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IEXEC)
    return str(path)


def test_openclaw_hm_arch_wiring_uses_state_dir_config_and_child_env(
    tmp_path: Path,
) -> None:
    env_probe = tmp_path / "openclaw-env-probe"
    env_capture = tmp_path / "child-env.txt"
    executable = _write_openclaw_env_probe(env_probe, capture_path=env_capture)

    workspace = AgentWorkspace.create(AgentKind.OPENCLAW, parent=tmp_path)
    storage_dir = tmp_path / "storage"
    storage_dir.mkdir()
    config = BenchmarkRunConfig(
        family=BenchmarkFamily.LOCOMO,
        agent=AgentKind.OPENCLAW,
        backend=MemoryBackendKind.HM_ARCH,
        use_mock_agent=False,
        agent_executable=executable,
    )
    runner = OpenClawCliAgentRunner(
        AgentRunnerContext(
            workspace=workspace,
            config=config,
            storage_dir=storage_dir,
            executable=executable,
        )
    )
    expected_config = openclaw_benchmark_config_path(workspace.agent_home)
    expected_plugin = (
        workspace.agent_home / "extensions" / HM_ARCH_PLUGIN_ID / "openclaw.plugin.json"
    )
    project_config = workspace.workspace / ".openclaw" / "openclaw.json"

    try:
        runner.open()
        assert expected_config.is_file(), "state config must exist under OPENCLAW_STATE_DIR"
        assert expected_plugin.is_file(), "plugin manifest must live under state config root"
        assert not project_config.exists(), "project-scoped config must not be used for wiring"

        openclaw_config = load_openclaw_config(expected_config)
        plugin_settings = (
            openclaw_config.get("plugins", {})
            .get("entries", {})
            .get(HM_ARCH_PLUGIN_ID, {})
            .get("config", {})
        )
        assert plugin_settings.get("dbPath") == hm_arch_db_path_str(storage_dir)

        child_env = hm_arch_cli_env(
            storage_dir,
            config,
            agent_home=workspace.agent_home,
        )
        assert child_env["OPENCLAW_CONFIG_PATH"] == str(expected_config)
        assert child_env["HM_ARCH_DB_PATH"] == hm_arch_db_path_str(storage_dir)
        assert os.environ.get("OPENCLAW_STATE_DIR") == str(workspace.agent_home)

        outcome = runner.answer(
            locomo_fixture().queries[0],
            recalled_context="should-not-be-injected",
            seed=0,
        )
    finally:
        runner.close()
        workspace.cleanup()

    assert outcome.failure_count == 0
    assert env_capture.is_file()
    captured = dict(
        line.split("=", 1)
        for line in env_capture.read_text(encoding="utf-8").splitlines()
        if "=" in line
    )
    assert captured["OPENCLAW_STATE_DIR"] == str(workspace.agent_home)
    assert captured["OPENCLAW_CONFIG_PATH"] == str(expected_config)
    assert captured["HM_ARCH_DB_PATH"] == hm_arch_db_path_str(storage_dir)


def test_unsupported_cli_executable_fails_at_open(tmp_path: Path) -> None:
    bad_cli = tmp_path / "unsupported-cli"
    bad_cli.write_text("#!/bin/sh\nexit 2\n", encoding="utf-8")
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
    runner = CodexCliAgentRunner(
        AgentRunnerContext(
            workspace=workspace,
            config=config,
            storage_dir=storage_dir,
            executable=str(bad_cli),
        )
    )
    try:
        with pytest.raises(NotImplementedError, match="CLI boundary is unavailable"):
            runner.open()
    finally:
        workspace.cleanup()
