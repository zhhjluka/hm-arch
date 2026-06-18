"""Memory backend factory registry."""

from __future__ import annotations

from typing import Callable

from ..compatibility import assert_supported
from ..protocol import MemoryBackend
from ..types import AgentKind, MemoryBackendKind
from .hm_arch import HmArchBackend
from .mem0 import Mem0Backend
from .native_memory import NativeMemoryBackend
from .no_memory import NoMemoryBackend
from .openviking import OpenVikingBackend

_BackendFactory = Callable[[], MemoryBackend]

_REGISTRY: dict[MemoryBackendKind, _BackendFactory] = {
    MemoryBackendKind.NO_MEMORY: NoMemoryBackend,
    MemoryBackendKind.HM_ARCH: HmArchBackend,
    MemoryBackendKind.NATIVE_MEMORY: NativeMemoryBackend,
    MemoryBackendKind.OPENVIKING: OpenVikingBackend,
    MemoryBackendKind.MEM0: Mem0Backend,
}


def register_memory_backend(
    kind: MemoryBackendKind, factory: _BackendFactory
) -> None:
    """Register or override a backend implementation."""
    _REGISTRY[kind] = factory


def create_memory_backend(
    kind: MemoryBackendKind,
    *,
    agent: AgentKind | None = None,
) -> MemoryBackend:
    if agent is not None:
        assert_supported(kind, agent)
    try:
        factory = _REGISTRY[kind]
    except KeyError as exc:
        raise ValueError(f"Unknown memory backend: {kind}") from exc
    return factory()
