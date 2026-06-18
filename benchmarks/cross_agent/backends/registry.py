"""Memory backend factory registry."""

from __future__ import annotations

from typing import Callable

from ..protocol import MemoryBackend
from ..types import MemoryBackendKind
from .hm_arch import HmArchBackend
from .no_memory import NoMemoryBackend
from .stub import StubMemoryBackend

_BackendFactory = Callable[[], MemoryBackend]

_REGISTRY: dict[MemoryBackendKind, _BackendFactory] = {
    MemoryBackendKind.NO_MEMORY: NoMemoryBackend,
    MemoryBackendKind.HM_ARCH: HmArchBackend,
    MemoryBackendKind.NATIVE_MEMORY: lambda: StubMemoryBackend(
        MemoryBackendKind.NATIVE_MEMORY
    ),
    MemoryBackendKind.OPENVIKING: lambda: StubMemoryBackend(MemoryBackendKind.OPENVIKING),
    MemoryBackendKind.MEM0: lambda: StubMemoryBackend(MemoryBackendKind.MEM0),
}


def register_memory_backend(
    kind: MemoryBackendKind, factory: _BackendFactory
) -> None:
    """Register or override a backend implementation."""
    _REGISTRY[kind] = factory


def create_memory_backend(kind: MemoryBackendKind) -> MemoryBackend:
    try:
        factory = _REGISTRY[kind]
    except KeyError as exc:
        raise ValueError(f"Unknown memory backend: {kind}") from exc
    return factory()
