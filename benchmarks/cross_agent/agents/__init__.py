"""Agent runner adapters for cross-agent benchmarks."""

from __future__ import annotations

from .registry import create_agent_runner, register_agent_runner
from .synthetic import SyntheticAgentRunner

__all__ = [
    "SyntheticAgentRunner",
    "create_agent_runner",
    "register_agent_runner",
]
