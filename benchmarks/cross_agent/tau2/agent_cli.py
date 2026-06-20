"""Production agent CLI availability checks for tau2 REAL mode."""

from __future__ import annotations

import re
from pathlib import Path

from ..agents.cli_process import resolve_agent_executable
from ..agents.cli_runner import (
    AgentRunnerContext,
    ClaudeCodeCliAgentRunner,
    CodexCliAgentRunner,
    HermesCliAgentRunner,
)
from ..agents.workspace import AgentWorkspace
from ..types import AgentKind, BenchmarkFamily, BenchmarkRunConfig, MemoryBackendKind

_HARNESS_EXECUTABLE_MARKERS = (
    "fake_tau2_agent_cli",
    "hm-arch-benchmark",
)
_AUTH_FAILURE_PATTERNS = re.compile(
    r"(not logged in|login required|authentication failed|unauthorized|"
    r"invalid api key|api key.*(missing|required|invalid)|"
    r"please (log in|sign in|authenticate))",
    re.IGNORECASE,
)

_CLI_RUNNERS = {
    AgentKind.CODEX: CodexCliAgentRunner,
    AgentKind.CLAUDE_CODE: ClaudeCodeCliAgentRunner,
    AgentKind.HERMES: HermesCliAgentRunner,
}

_DEFAULT_EXECUTABLE_NAMES = {
    AgentKind.CODEX: ("codex",),
    AgentKind.CLAUDE_CODE: ("claude",),
    AgentKind.HERMES: ("hermes",),
}


def is_harness_executable(executable: str | None) -> bool:
    """Return whether *executable* is a labeled harness/test double."""
    if not executable:
        return False
    normalized = str(Path(executable).name).lower()
    if "fake" in normalized and "tau2" in normalized:
        return True
    return any(marker in executable for marker in _HARNESS_EXECUTABLE_MARKERS)


def classify_cli_failure(stderr: str, stdout: str = "") -> str | None:
    """Return an auth/login failure label when CLI output indicates one."""
    combined = f"{stderr}\n{stdout}".strip()
    if not combined:
        return None
    if _AUTH_FAILURE_PATTERNS.search(combined):
        return "agent_cli_auth_failure"
    return None


def production_cli_status(
    agent: AgentKind,
    *,
    executable_override: str | None = None,
) -> tuple[str, str]:
    """Return (status, rationale) for a production CLI boundary.

    status is one of: ready, unavailable, failed
    """
    if agent is AgentKind.OPENCLAW:
        return "unavailable", "OpenClaw production CLI deferred pending MEM-75"

    if is_harness_executable(executable_override):
        return "failed", "REAL mode cannot use harness or fake agent executables"

    runner_cls = _CLI_RUNNERS.get(agent)
    default_names = _DEFAULT_EXECUTABLE_NAMES.get(agent, ())
    if runner_cls is None:
        return "unavailable", f"No production CLI runner for agent {agent.value}"

    executable = resolve_agent_executable(
        agent.value,
        override=executable_override,
        default_names=default_names,
    )
    if executable is None:
        return (
            "unavailable",
            f"{agent.value} production CLI not found on PATH "
            f"(expected one of: {', '.join(default_names) or 'n/a'})",
        )

    if is_harness_executable(executable):
        return "failed", f"Resolved executable is a harness double: {executable}"

    workspace = AgentWorkspace.create(agent, run_id="tau2-cli-probe", parent=Path.cwd())
    config = BenchmarkRunConfig(
        family=BenchmarkFamily.TAU2_BENCH,
        agent=agent,
        backend=MemoryBackendKind.NO_MEMORY,
        seed=0,
        use_mock_agent=False,
        agent_executable=executable_override,
    )
    context = AgentRunnerContext(
        workspace=workspace,
        config=config,
        storage_dir=workspace.workspace / "storage",
        executable=executable_override,
    )
    runner = runner_cls(context)
    try:
        runner.open()
    except NotImplementedError as exc:
        return "unavailable", str(exc)
    except Exception as exc:  # noqa: BLE001
        return "failed", f"CLI probe failed for {agent.value}: {exc}"
    finally:
        try:
            runner.close()
        except Exception:  # noqa: BLE001
            pass
        workspace.cleanup()

    if runner._cli_mode != "real":  # noqa: SLF001 — probe result
        return (
            "unavailable",
            f"{agent.value} executable only exposes hm-arch-benchmark test double, "
            "not a production one-shot CLI",
        )
    return "ready", f"production CLI resolved: {executable}"
