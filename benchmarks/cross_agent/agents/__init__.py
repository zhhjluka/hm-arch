"""Agent runner adapters for cross-agent benchmarks."""

from __future__ import annotations

from .cli_runner import (
    AgentRunnerContext,
    ClaudeCodeCliAgentRunner,
    CodexCliAgentRunner,
    HermesCliAgentRunner,
    OpenClawCliAgentRunner,
)
from .registry import create_agent_runner, is_supported_coordinate, register_agent_runner
from .synthetic import MockSyntheticAgentRunner, SyntheticAgentRunner

__all__ = [
    "AgentRunnerContext",
    "ClaudeCodeCliAgentRunner",
    "CodexCliAgentRunner",
    "HermesCliAgentRunner",
    "MockSyntheticAgentRunner",
    "OpenClawCliAgentRunner",
    "SyntheticAgentRunner",
    "create_agent_runner",
    "is_supported_coordinate",
    "register_agent_runner",
]
