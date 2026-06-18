"""Provider/agent compatibility matrix for cross-agent benchmarks."""

from __future__ import annotations

from dataclasses import dataclass

from .types import AgentKind, MemoryBackendKind, UnsupportedCombinationError


@dataclass(frozen=True)
class CompatibilityCell:
    """One provider/agent matrix entry."""

    supported: bool
    reason: str | None = None
    requires_external_service: bool = False


def _all_agents() -> tuple[AgentKind, ...]:
    return tuple(AgentKind)


_COMPATIBILITY: dict[tuple[MemoryBackendKind, AgentKind], CompatibilityCell] = {
    **{
        (MemoryBackendKind.NO_MEMORY, agent): CompatibilityCell(supported=True)
        for agent in _all_agents()
    },
    **{
        (MemoryBackendKind.HM_ARCH, agent): CompatibilityCell(supported=True)
        for agent in _all_agents()
    },
    **{
        (MemoryBackendKind.MOCK, agent): CompatibilityCell(
            supported=True,
            reason="Explicit mock backend for offline contract tests only.",
        )
        for agent in _all_agents()
    },
    **{
        (MemoryBackendKind.NATIVE_MEMORY, agent): CompatibilityCell(
            supported=True,
            reason="Requires the agent runner to expose a native-memory bridge.",
        )
        for agent in _all_agents()
    },
    (MemoryBackendKind.MEM0, AgentKind.HERMES): CompatibilityCell(
        supported=True,
        requires_external_service=True,
        reason="Requires mem0ai and a configured Mem0 provider.",
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


def compatibility_cell(
    backend: MemoryBackendKind,
    agent: AgentKind,
) -> CompatibilityCell:
    """Return the matrix cell for *backend* and *agent*."""
    return _COMPATIBILITY[(backend, agent)]


def assert_supported(backend: MemoryBackendKind, agent: AgentKind) -> None:
    """Raise when the requested provider/agent pair is unsupported."""
    cell = compatibility_cell(backend, agent)
    if not cell.supported:
        raise UnsupportedCombinationError(
            f"Backend {backend.value!r} is not supported for agent "
            f"{agent.value!r}: {cell.reason}"
        )


def supported_pairs() -> list[tuple[MemoryBackendKind, AgentKind]]:
    """Return all supported backend/agent combinations."""
    return [
        (backend, agent)
        for (backend, agent), cell in _COMPATIBILITY.items()
        if cell.supported
    ]


def unsupported_pairs() -> list[tuple[MemoryBackendKind, AgentKind, str]]:
    """Return unsupported combinations with human-readable reasons."""
    return [
        (backend, agent, cell.reason or "unsupported")
        for (backend, agent), cell in _COMPATIBILITY.items()
        if not cell.supported
    ]
