"""Agent runner adapters for cross-agent benchmarks."""

from __future__ import annotations

from .registry import create_agent_runner, is_supported_coordinate, register_agent_runner
from .synthetic import MockSyntheticAgentRunner, SyntheticAgentRunner

__all__ = [
    "MockSyntheticAgentRunner",
    "SyntheticAgentRunner",
    "create_agent_runner",
    "is_supported_coordinate",
    "register_agent_runner",
]
