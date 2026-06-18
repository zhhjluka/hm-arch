"""Factory helpers for benchmark memory backends."""

from __future__ import annotations

from typing import Any

from .backends import (
    HMArchMemoryBackend,
    Mem0MemoryBackend,
    NativeMemoryBackend,
    NoMemoryBackend,
    OpenVikingMemoryBackend,
)
from .compatibility import assert_supported, compatibility_cell, supported_pairs, unsupported_pairs
from .contract import (
    AgentId,
    MemoryBackend,
    MemoryBackendRunConfig,
    MemoryProviderId,
    UnsupportedCombinationError,
)

_BACKEND_TYPES = {
    MemoryProviderId.NO_MEMORY: NoMemoryBackend,
    MemoryProviderId.HM_ARCH: HMArchMemoryBackend,
    MemoryProviderId.MEM0: Mem0MemoryBackend,
    MemoryProviderId.OPENVIKING: OpenVikingMemoryBackend,
    MemoryProviderId.NATIVE_MEMORY: NativeMemoryBackend,
}


def create_memory_backend(
    config: MemoryBackendRunConfig,
    **kwargs: Any,
) -> MemoryBackend:
    """Instantiate a provider backend for *config* after matrix validation."""
    assert_supported(config.provider_id, config.agent_id)
    backend_cls = _BACKEND_TYPES[config.provider_id]
    return backend_cls(config, **kwargs)


def list_provider_ids() -> list[str]:
    """Return registered provider identifiers."""
    return [provider.value for provider in MemoryProviderId]


__all__ = [
    "UnsupportedCombinationError",
    "assert_supported",
    "compatibility_cell",
    "create_memory_backend",
    "list_provider_ids",
    "supported_pairs",
    "unsupported_pairs",
]
