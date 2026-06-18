"""Provider/agent compatibility matrix for cross-agent benchmarks."""

from __future__ import annotations

from dataclasses import dataclass

from .contract import AgentId, MemoryProviderId, UnsupportedCombinationError


@dataclass(frozen=True)
class CompatibilityCell:
    """One provider/agent matrix entry."""

    supported: bool
    reason: str | None = None
    requires_external_service: bool = False


def _all_agents() -> tuple[AgentId, ...]:
    return tuple(AgentId)


_COMPATIBILITY: dict[tuple[MemoryProviderId, AgentId], CompatibilityCell] = {
    # no-memory control works with every agent runner.
    **{
        (MemoryProviderId.NO_MEMORY, agent): CompatibilityCell(supported=True)
        for agent in _all_agents()
    },
    # HM-Arch ships first-class integrations for all current agents.
    **{
        (MemoryProviderId.HM_ARCH, agent): CompatibilityCell(supported=True)
        for agent in _all_agents()
    },
    # Native memory is agent-owned; the harness only records the mode.
    **{
        (MemoryProviderId.NATIVE_MEMORY, agent): CompatibilityCell(supported=True)
        for agent in _all_agents()
    },
    # Mem0 is meaningful for Hermes and OpenClaw; hook agents have no Mem0 slot.
    (MemoryProviderId.MEM0, AgentId.HERMES): CompatibilityCell(
        supported=True,
        requires_external_service=True,
        reason="Requires mem0ai and a configured Mem0 provider in Hermes.",
    ),
    (MemoryProviderId.MEM0, AgentId.OPENCLAW): CompatibilityCell(
        supported=True,
        requires_external_service=True,
        reason="Requires mem0ai and an OpenClaw Mem0 plugin configuration.",
    ),
    (MemoryProviderId.MEM0, AgentId.CODEX): CompatibilityCell(
        supported=False,
        reason="Codex has no Mem0 hook or memory provider slot.",
    ),
    (MemoryProviderId.MEM0, AgentId.CLAUDE_CODE): CompatibilityCell(
        supported=False,
        reason="Claude Code has no Mem0 hook or memory provider slot.",
    ),
    # OpenViking targets OpenClaw first; other agents lack a packaged integration.
    (MemoryProviderId.OPENVIKING, AgentId.OPENCLAW): CompatibilityCell(
        supported=True,
        requires_external_service=True,
        reason="Requires openviking embedded storage or a reachable OpenViking service.",
    ),
    (MemoryProviderId.OPENVIKING, AgentId.HERMES): CompatibilityCell(
        supported=False,
        reason="Hermes has no packaged OpenViking memory provider.",
    ),
    (MemoryProviderId.OPENVIKING, AgentId.CODEX): CompatibilityCell(
        supported=False,
        reason="Codex has no OpenViking hook integration.",
    ),
    (MemoryProviderId.OPENVIKING, AgentId.CLAUDE_CODE): CompatibilityCell(
        supported=False,
        reason="Claude Code has no OpenViking hook integration.",
    ),
}


def compatibility_cell(
    provider_id: MemoryProviderId,
    agent_id: AgentId,
) -> CompatibilityCell:
    """Return the matrix cell for *provider_id* and *agent_id*."""
    return _COMPATIBILITY[(provider_id, agent_id)]


def assert_supported(provider_id: MemoryProviderId, agent_id: AgentId) -> None:
    """Raise when the requested provider/agent pair is unsupported."""
    cell = compatibility_cell(provider_id, agent_id)
    if not cell.supported:
        raise UnsupportedCombinationError(
            f"Provider {provider_id.value!r} is not supported for agent "
            f"{agent_id.value!r}: {cell.reason}"
        )


def supported_pairs() -> list[tuple[MemoryProviderId, AgentId]]:
    """Return all supported provider/agent combinations."""
    return [
        (provider_id, agent_id)
        for (provider_id, agent_id), cell in _COMPATIBILITY.items()
        if cell.supported
    ]


def unsupported_pairs() -> list[tuple[MemoryProviderId, AgentId, str]]:
    """Return unsupported combinations with human-readable reasons."""
    return [
        (provider_id, agent_id, cell.reason or "unsupported")
        for (provider_id, agent_id), cell in _COMPATIBILITY.items()
        if not cell.supported
    ]
