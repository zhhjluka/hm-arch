"""Agent handler registry for integration management CLI."""

from __future__ import annotations

from .claude_code import ClaudeCodeAgentHandler
from .codex import CodexAgentHandler
from .hermes import HermesAgentHandler
from .openclaw import OpenClawAgentHandler
from .types import AgentHandler

ALL_AGENTS: tuple[str, ...] = ("codex", "claude-code", "hermes", "openclaw")
INSTALLABLE_AGENTS: tuple[str, ...] = ("codex", "claude-code")

_HANDLERS: dict[str, AgentHandler] = {
    "codex": CodexAgentHandler(),
    "claude-code": ClaudeCodeAgentHandler(),
    "hermes": HermesAgentHandler(),
    "openclaw": OpenClawAgentHandler(),
}


def list_agents() -> tuple[str, ...]:
    """Return supported agent identifiers."""
    return ALL_AGENTS


def get_agent_handler(agent: str) -> AgentHandler:
    """Return the handler for *agent* or raise ``KeyError``."""
    try:
        return _HANDLERS[agent]
    except KeyError as exc:
        raise KeyError(
            f"Unsupported agent {agent!r}; choose from: {', '.join(ALL_AGENTS)}"
        ) from exc
