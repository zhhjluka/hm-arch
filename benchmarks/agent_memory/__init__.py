"""Cross-agent memory benchmark backends (HM-72 / MEM-73)."""

from .backends import (
    AgentNativeMemoryBridge,
    HMArchMemoryBackend,
    Mem0MemoryBackend,
    NativeMemoryBackend,
    NoMemoryBackend,
    OfflineMem0Client,
    OfflineOpenVikingClient,
    OpenVikingMemoryBackend,
)
from .compatibility import (
    assert_supported,
    compatibility_cell,
    supported_pairs,
    unsupported_pairs,
)
from .contract import (
    AgentId,
    ConsolidateResult,
    IngestResult,
    IngestTurn,
    MemoryBackend,
    MemoryBackendRunConfig,
    MemoryProviderId,
    ProviderOperationMetrics,
    RecallResult,
    UnsupportedCombinationError,
)
from .registry import create_memory_backend, list_provider_ids

__all__ = [
    "AgentId",
    "AgentNativeMemoryBridge",
    "ConsolidateResult",
    "HMArchMemoryBackend",
    "IngestResult",
    "IngestTurn",
    "Mem0MemoryBackend",
    "MemoryBackend",
    "MemoryBackendRunConfig",
    "MemoryProviderId",
    "NativeMemoryBackend",
    "NoMemoryBackend",
    "OfflineMem0Client",
    "OfflineOpenVikingClient",
    "OpenVikingMemoryBackend",
    "ProviderOperationMetrics",
    "RecallResult",
    "UnsupportedCombinationError",
    "assert_supported",
    "compatibility_cell",
    "create_memory_backend",
    "list_provider_ids",
    "supported_pairs",
    "unsupported_pairs",
]
