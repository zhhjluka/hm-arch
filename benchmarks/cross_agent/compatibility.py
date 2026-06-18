"""Provider/agent compatibility matrix for cross-agent benchmarks.

Two views share one coordinate space:

* **Backend compatibility** — whether a memory provider can run for an agent pair.
  Enforced via :func:`assert_supported` when creating backends.
* **Agent runner implementation** — whether production CLI runners can drive a
  cell (``real``), only offline mocks (``mock_only``), or neither (``unsupported``).
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from .types import AgentKind, MemoryBackendKind


class CellImplementation(str, Enum):
    """How a matrix cell is executed by production CLI agent runners."""

    REAL = "real"
    MOCK_ONLY = "mock_only"
    UNSUPPORTED = "unsupported"


@dataclass(frozen=True)
class CompatibilityCell:
    """Backend-level matrix entry."""

    supported: bool
    reason: str | None = None
    requires_external_service: bool = False


@dataclass(frozen=True)
class MatrixCell:
    """Agent-runner implementation for one agent × backend coordinate."""

    agent: AgentKind
    backend: MemoryBackendKind
    implementation: CellImplementation
    rationale: str


class UnsupportedCombinationError(ValueError):
    """Raised when a provider/agent pair is not supported by the benchmark matrix."""


def _all_agents() -> tuple[AgentKind, ...]:
    return tuple(AgentKind)


_BACKEND_COMPATIBILITY: dict[tuple[MemoryBackendKind, AgentKind], CompatibilityCell] = {
    **{
        (MemoryBackendKind.NO_MEMORY, agent): CompatibilityCell(supported=True)
        for agent in _all_agents()
    },
    **{
        (MemoryBackendKind.HM_ARCH, agent): CompatibilityCell(supported=True)
        for agent in _all_agents()
    },
    **{
        (MemoryBackendKind.NATIVE_MEMORY, agent): CompatibilityCell(supported=True)
        for agent in _all_agents()
    },
    (MemoryBackendKind.MEM0, AgentKind.HERMES): CompatibilityCell(
        supported=True,
        requires_external_service=True,
        reason="Requires mem0ai and a configured Mem0 provider in Hermes.",
    ),
    (MemoryBackendKind.MEM0, AgentKind.OPENCLAW): CompatibilityCell(
        supported=True,
        requires_external_service=True,
        reason="Requires mem0ai and an OpenClaw Mem0 plugin configuration.",
    ),
    (MemoryBackendKind.MEM0, AgentKind.CODEX): CompatibilityCell(
        supported=False,
        reason="Codex has no Mem0 hook or memory provider slot.",
    ),
    (MemoryBackendKind.MEM0, AgentKind.CLAUDE_CODE): CompatibilityCell(
        supported=False,
        reason="Claude Code has no Mem0 hook or memory provider slot.",
    ),
    (MemoryBackendKind.OPENVIKING, AgentKind.OPENCLAW): CompatibilityCell(
        supported=True,
        requires_external_service=True,
        reason="Requires openviking embedded storage or a reachable OpenViking service.",
    ),
    (MemoryBackendKind.OPENVIKING, AgentKind.HERMES): CompatibilityCell(
        supported=False,
        reason="Hermes has no packaged OpenViking memory provider.",
    ),
    (MemoryBackendKind.OPENVIKING, AgentKind.CODEX): CompatibilityCell(
        supported=False,
        reason="Codex has no OpenViking hook integration.",
    ),
    (MemoryBackendKind.OPENVIKING, AgentKind.CLAUDE_CODE): CompatibilityCell(
        supported=False,
        reason="Claude Code has no OpenViking hook integration.",
    ),
}


def matrix_key(agent: AgentKind, backend: MemoryBackendKind) -> str:
    return f"{agent.value}|{backend.value}"


_AGENT_MATRIX: dict[str, MatrixCell] = {
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
        "Mem0 backend exists but Codex has no Mem0 hook slot.",
    ),
    matrix_key(AgentKind.CODEX, MemoryBackendKind.OPENVIKING): MatrixCell(
        AgentKind.CODEX,
        MemoryBackendKind.OPENVIKING,
        CellImplementation.UNSUPPORTED,
        "OpenViking backend exists but Codex has no OpenViking hook integration.",
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
        "Mem0 backend exists but Claude Code has no Mem0 hook slot.",
    ),
    matrix_key(AgentKind.CLAUDE_CODE, MemoryBackendKind.OPENVIKING): MatrixCell(
        AgentKind.CLAUDE_CODE,
        MemoryBackendKind.OPENVIKING,
        CellImplementation.UNSUPPORTED,
        "OpenViking backend exists but Claude Code has no OpenViking hook integration.",
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
        "Mem0 backend exists; CLI runners do not configure Hermes Mem0 provider yet.",
    ),
    matrix_key(AgentKind.HERMES, MemoryBackendKind.OPENVIKING): MatrixCell(
        AgentKind.HERMES,
        MemoryBackendKind.OPENVIKING,
        CellImplementation.UNSUPPORTED,
        "OpenViking backend exists but Hermes has no packaged OpenViking provider.",
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
        "Mem0 backend exists; CLI runners do not configure OpenClaw Mem0 plugin yet.",
    ),
    matrix_key(AgentKind.OPENCLAW, MemoryBackendKind.OPENVIKING): MatrixCell(
        AgentKind.OPENCLAW,
        MemoryBackendKind.OPENVIKING,
        CellImplementation.UNSUPPORTED,
        "OpenViking backend exists; CLI runners do not configure OpenClaw OpenViking plugin yet.",
    ),
}


def compatibility_cell(
    backend: MemoryBackendKind,
    agent: AgentKind,
) -> CompatibilityCell:
    """Return the backend compatibility cell for *backend* and *agent*."""
    return _BACKEND_COMPATIBILITY[(backend, agent)]


def assert_supported(backend: MemoryBackendKind, agent: AgentKind) -> None:
    """Raise when the requested provider/agent pair is unsupported at backend level."""
    cell = compatibility_cell(backend, agent)
    if not cell.supported:
        raise UnsupportedCombinationError(
            f"Memory backend {backend.value!r} is not supported for agent "
            f"{agent.value!r}: {cell.reason}"
        )


def supported_pairs() -> list[tuple[MemoryBackendKind, AgentKind]]:
    """Return all backend-supported provider/agent combinations."""
    return [
        (backend, agent)
        for (backend, agent), cell in _BACKEND_COMPATIBILITY.items()
        if cell.supported
    ]


def unsupported_pairs() -> list[tuple[MemoryBackendKind, AgentKind, str]]:
    """Return backend-unsupported combinations with human-readable reasons."""
    return [
        (backend, agent, cell.reason or "unsupported")
        for (backend, agent), cell in _BACKEND_COMPATIBILITY.items()
        if not cell.supported
    ]


def lookup_matrix_cell(agent: AgentKind, backend: MemoryBackendKind) -> MatrixCell:
    """Return the agent-runner implementation cell for *agent* and *backend*."""
    key = matrix_key(agent, backend)
    return _AGENT_MATRIX.get(
        key,
        MatrixCell(
            agent,
            backend,
            CellImplementation.UNSUPPORTED,
            "Combination not declared in compatibility matrix.",
        ),
    )


def compatibility_snapshot() -> dict[str, str]:
    """Export agent-runner matrix implementation labels for reports."""
    return {key: cell.implementation.value for key, cell in _AGENT_MATRIX.items()}


def smoke_matrix_configs() -> list[tuple[AgentKind, MemoryBackendKind]]:
    """Default smoke coordinates: each agent in HM-Arch and no-memory modes."""
    configs: list[tuple[AgentKind, MemoryBackendKind]] = []
    for agent in AgentKind:
        configs.append((agent, MemoryBackendKind.NO_MEMORY))
        configs.append((agent, MemoryBackendKind.HM_ARCH))
    return configs
