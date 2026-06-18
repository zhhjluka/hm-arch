"""Agent runner factory registry."""

from __future__ import annotations

from typing import Callable

from ..compatibility import CellImplementation, lookup_matrix_cell
from ..protocol import AgentRunner
from ..types import AgentKind, BenchmarkRunConfig
from .cli_runner import (
    AgentRunnerContext,
    ClaudeCodeCliAgentRunner,
    CodexCliAgentRunner,
    HermesCliAgentRunner,
    OpenClawCliAgentRunner,
)
from .synthetic import MockSyntheticAgentRunner

_AgentFactory = Callable[[AgentRunnerContext], AgentRunner]

_CLI_RUNNERS: dict[AgentKind, type] = {
    AgentKind.CODEX: CodexCliAgentRunner,
    AgentKind.CLAUDE_CODE: ClaudeCodeCliAgentRunner,
    AgentKind.HERMES: HermesCliAgentRunner,
    AgentKind.OPENCLAW: OpenClawCliAgentRunner,
}

_REGISTRY: dict[AgentKind, _AgentFactory] = {}


def _default_factory(kind: AgentKind) -> _AgentFactory:
    def _create(context: AgentRunnerContext) -> AgentRunner:
        if context.config.use_mock_agent:
            return MockSyntheticAgentRunner(context.workspace, context.config)
        runner_cls = _CLI_RUNNERS[kind]
        return runner_cls(context)

    return _create


for _kind in AgentKind:
    _REGISTRY[_kind] = _default_factory(_kind)


def register_agent_runner(kind: AgentKind, factory: _AgentFactory) -> None:
    _REGISTRY[kind] = factory


def create_agent_runner(
    kind: AgentKind,
    *,
    context: AgentRunnerContext | None = None,
    config: BenchmarkRunConfig | None = None,
    workspace=None,
) -> AgentRunner:
    """Create an agent runner for *kind*.

    Production callers should pass *context* with workspace and config.
    Legacy callers passing only *kind* receive a mock runner for offline tests.
    """
    if context is None:
        if config is not None and workspace is not None:
            context = AgentRunnerContext(workspace=workspace, config=config)
        else:
            return MockSyntheticAgentRunner()

    try:
        factory = _REGISTRY[kind]
    except KeyError as exc:
        raise ValueError(f"Unknown agent kind: {kind}") from exc
    return factory(context)


def is_supported_coordinate(config: BenchmarkRunConfig) -> tuple[bool, str]:
    """Return whether *config* is supported and the matrix rationale."""
    cell = lookup_matrix_cell(config.agent, config.backend)
    if config.use_mock_agent:
        return True, "mock runner enabled for offline harness tests"
    if cell.implementation is CellImplementation.UNSUPPORTED:
        return False, cell.rationale
    return True, cell.rationale
