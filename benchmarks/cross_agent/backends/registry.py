"""Memory backend factory registry."""

from __future__ import annotations

from typing import Callable

from ..compatibility import assert_supported
from ..protocol import AgentNativeMemoryBridge, MemoryBackend
from ..types import BenchmarkRunConfig, MemoryBackendKind
from .hm_arch import HmArchBackend
from .mem0 import Mem0Backend
from .mock import MockMemoryBackend
from .native import NativeMemoryBackend
from .no_memory import NoMemoryBackend
from .openviking import OpenVikingBackend

_BackendFactory = Callable[[BenchmarkRunConfig, AgentNativeMemoryBridge | None], MemoryBackend]

_REGISTRY: dict[MemoryBackendKind, _BackendFactory] = {
    MemoryBackendKind.NO_MEMORY: lambda _config, _bridge: NoMemoryBackend(),
    MemoryBackendKind.HM_ARCH: lambda _config, _bridge: HmArchBackend(),
    MemoryBackendKind.MEM0: lambda _config, _bridge: Mem0Backend(),
    MemoryBackendKind.OPENVIKING: lambda _config, _bridge: OpenVikingBackend(),
    MemoryBackendKind.MOCK: lambda _config, _bridge: MockMemoryBackend(),
    MemoryBackendKind.NATIVE_MEMORY: lambda _config, bridge: NativeMemoryBackend(
        bridge=bridge
    ),
}


def register_memory_backend(
    kind: MemoryBackendKind, factory: _BackendFactory
) -> None:
    """Register or override a backend implementation."""
    _REGISTRY[kind] = factory


def create_memory_backend(
    kind: MemoryBackendKind,
    config: BenchmarkRunConfig,
    *,
    native_bridge: AgentNativeMemoryBridge | None = None,
) -> MemoryBackend:
    """Instantiate a backend after validating the provider/agent matrix."""
    assert_supported(kind, config.agent)
    try:
        factory = _REGISTRY[kind]
    except KeyError as exc:
        raise ValueError(f"Unknown memory backend: {kind}") from exc
    return factory(config, native_bridge)
