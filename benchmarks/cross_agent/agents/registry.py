"""Agent runner factory registry."""

from __future__ import annotations

from typing import Callable

from ..protocol import AgentRunner
from ..types import AgentKind
from .synthetic import SyntheticAgentRunner

_AgentFactory = Callable[[], AgentRunner]

_REGISTRY: dict[AgentKind, _AgentFactory] = {
    AgentKind.OPENCLAW: SyntheticAgentRunner,
    AgentKind.HERMES: SyntheticAgentRunner,
    AgentKind.CLAUDE_CODE: SyntheticAgentRunner,
    AgentKind.CODEX: SyntheticAgentRunner,
}


def register_agent_runner(kind: AgentKind, factory: _AgentFactory) -> None:
    _REGISTRY[kind] = factory


def create_agent_runner(kind: AgentKind) -> AgentRunner:
    try:
        factory = _REGISTRY[kind]
    except KeyError as exc:
        raise ValueError(f"Unknown agent kind: {kind}") from exc
    return factory()
