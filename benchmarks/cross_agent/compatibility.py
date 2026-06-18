"""Agent × memory compatibility matrix for cross-agent benchmarks."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from .types import AgentKind, MemoryBackendKind  # noqa: TID252 — sibling module


class CellImplementation(str, Enum):
    """How a matrix cell is executed in this repository."""

    REAL = "real"
    MOCK_ONLY = "mock_only"
    UNSUPPORTED = "unsupported"


@dataclass(frozen=True)
class MatrixCell:
    """One agent × backend coordinate."""

    agent: AgentKind
    backend: MemoryBackendKind
    implementation: CellImplementation
    rationale: str


def matrix_key(agent: AgentKind, backend: MemoryBackendKind) -> str:
    return f"{agent.value}|{backend.value}"


_MATRIX: dict[str, MatrixCell] = {
    # Codex
    matrix_key(AgentKind.CODEX, MemoryBackendKind.NO_MEMORY): MatrixCell(
        AgentKind.CODEX,
        MemoryBackendKind.NO_MEMORY,
        CellImplementation.REAL,
        "Invoke codex CLI in isolated CODEX_HOME without HM-Arch hooks.",
    ),
    matrix_key(AgentKind.CODEX, MemoryBackendKind.NATIVE_MEMORY): MatrixCell(
        AgentKind.CODEX,
        MemoryBackendKind.NATIVE_MEMORY,
        CellImplementation.UNSUPPORTED,
        "Codex native memories require interactive CLI sessions; not driven by this harness yet.",
    ),
    matrix_key(AgentKind.CODEX, MemoryBackendKind.HM_ARCH): MatrixCell(
        AgentKind.CODEX,
        MemoryBackendKind.HM_ARCH,
        CellImplementation.REAL,
        "Install HM-Arch Codex hooks in isolated home; invoke codex CLI boundary.",
    ),
    matrix_key(AgentKind.CODEX, MemoryBackendKind.MEM0): MatrixCell(
        AgentKind.CODEX,
        MemoryBackendKind.MEM0,
        CellImplementation.UNSUPPORTED,
        "Mem0 adapter is not registered in this repository.",
    ),
    matrix_key(AgentKind.CODEX, MemoryBackendKind.OPENVIKING): MatrixCell(
        AgentKind.CODEX,
        MemoryBackendKind.OPENVIKING,
        CellImplementation.UNSUPPORTED,
        "OpenViking adapter is not registered in this repository.",
    ),
    # Claude Code
    matrix_key(AgentKind.CLAUDE_CODE, MemoryBackendKind.NO_MEMORY): MatrixCell(
        AgentKind.CLAUDE_CODE,
        MemoryBackendKind.NO_MEMORY,
        CellImplementation.REAL,
        "Invoke claude CLI in isolated CLAUDE_CONFIG_DIR without HM-Arch hooks.",
    ),
    matrix_key(AgentKind.CLAUDE_CODE, MemoryBackendKind.NATIVE_MEMORY): MatrixCell(
        AgentKind.CLAUDE_CODE,
        MemoryBackendKind.NATIVE_MEMORY,
        CellImplementation.UNSUPPORTED,
        "Claude Code native memory is not wired to the benchmark ingest lifecycle.",
    ),
    matrix_key(AgentKind.CLAUDE_CODE, MemoryBackendKind.HM_ARCH): MatrixCell(
        AgentKind.CLAUDE_CODE,
        MemoryBackendKind.HM_ARCH,
        CellImplementation.REAL,
        "Install HM-Arch Claude Code hooks in isolated home; invoke claude CLI boundary.",
    ),
    matrix_key(AgentKind.CLAUDE_CODE, MemoryBackendKind.MEM0): MatrixCell(
        AgentKind.CLAUDE_CODE,
        MemoryBackendKind.MEM0,
        CellImplementation.UNSUPPORTED,
        "Mem0 adapter is not registered in this repository.",
    ),
    matrix_key(AgentKind.CLAUDE_CODE, MemoryBackendKind.OPENVIKING): MatrixCell(
        AgentKind.CLAUDE_CODE,
        MemoryBackendKind.OPENVIKING,
        CellImplementation.UNSUPPORTED,
        "OpenViking adapter is not registered in this repository.",
    ),
    # Hermes
    matrix_key(AgentKind.HERMES, MemoryBackendKind.NO_MEMORY): MatrixCell(
        AgentKind.HERMES,
        MemoryBackendKind.NO_MEMORY,
        CellImplementation.REAL,
        "Invoke hermes CLI in isolated HERMES_HOME without durable memory provider.",
    ),
    matrix_key(AgentKind.HERMES, MemoryBackendKind.NATIVE_MEMORY): MatrixCell(
        AgentKind.HERMES,
        MemoryBackendKind.NATIVE_MEMORY,
        CellImplementation.UNSUPPORTED,
        "Hermes native memory provider is not automated in the benchmark harness.",
    ),
    matrix_key(AgentKind.HERMES, MemoryBackendKind.HM_ARCH): MatrixCell(
        AgentKind.HERMES,
        MemoryBackendKind.HM_ARCH,
        CellImplementation.REAL,
        "Install HM-Arch Hermes provider bridge; invoke hermes CLI boundary.",
    ),
    matrix_key(AgentKind.HERMES, MemoryBackendKind.MEM0): MatrixCell(
        AgentKind.HERMES,
        MemoryBackendKind.MEM0,
        CellImplementation.UNSUPPORTED,
        "Hermes doctor rejects active mem0 provider; use HM-Arch instead.",
    ),
    matrix_key(AgentKind.HERMES, MemoryBackendKind.OPENVIKING): MatrixCell(
        AgentKind.HERMES,
        MemoryBackendKind.OPENVIKING,
        CellImplementation.UNSUPPORTED,
        "OpenViking adapter is not registered in this repository.",
    ),
    # OpenClaw
    matrix_key(AgentKind.OPENCLAW, MemoryBackendKind.NO_MEMORY): MatrixCell(
        AgentKind.OPENCLAW,
        MemoryBackendKind.NO_MEMORY,
        CellImplementation.REAL,
        "Invoke openclaw CLI in isolated state dir without memory plugin slot.",
    ),
    matrix_key(AgentKind.OPENCLAW, MemoryBackendKind.NATIVE_MEMORY): MatrixCell(
        AgentKind.OPENCLAW,
        MemoryBackendKind.NATIVE_MEMORY,
        CellImplementation.UNSUPPORTED,
        "OpenClaw native memory plugin selection is not automated in the harness.",
    ),
    matrix_key(AgentKind.OPENCLAW, MemoryBackendKind.HM_ARCH): MatrixCell(
        AgentKind.OPENCLAW,
        MemoryBackendKind.HM_ARCH,
        CellImplementation.REAL,
        "Configure HM-Arch OpenClaw plugin slot; invoke openclaw CLI boundary.",
    ),
    matrix_key(AgentKind.OPENCLAW, MemoryBackendKind.MEM0): MatrixCell(
        AgentKind.OPENCLAW,
        MemoryBackendKind.MEM0,
        CellImplementation.UNSUPPORTED,
        "Mem0 adapter is not registered in this repository.",
    ),
    matrix_key(AgentKind.OPENCLAW, MemoryBackendKind.OPENVIKING): MatrixCell(
        AgentKind.OPENCLAW,
        MemoryBackendKind.OPENVIKING,
        CellImplementation.UNSUPPORTED,
        "OpenViking adapter is not registered in this repository.",
    ),
}


def lookup_matrix_cell(agent: AgentKind, backend: MemoryBackendKind) -> MatrixCell:
    key = matrix_key(agent, backend)
    return _MATRIX.get(
        key,
        MatrixCell(
            agent,
            backend,
            CellImplementation.UNSUPPORTED,
            "Combination not declared in compatibility matrix.",
        ),
    )


def compatibility_snapshot() -> dict[str, str]:
    """Export matrix implementation labels for reports."""
    return {key: cell.implementation.value for key, cell in _MATRIX.items()}


def smoke_matrix_configs() -> list[tuple[AgentKind, MemoryBackendKind]]:
    """Default smoke coordinates: each agent in HM-Arch and no-memory modes."""
    configs: list[tuple[AgentKind, MemoryBackendKind]] = []
    for agent in AgentKind:
        configs.append((agent, MemoryBackendKind.NO_MEMORY))
        configs.append((agent, MemoryBackendKind.HM_ARCH))
    return configs
