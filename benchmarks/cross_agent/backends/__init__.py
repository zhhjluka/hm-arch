"""Memory backend adapters for cross-agent benchmarks."""

from .errors import ProviderPackageRequired
from .hm_arch import HmArchBackend
from .mem0 import Mem0Backend, OfflineMem0Client, create_mem0_client
from .native_memory import AgentNativeMemoryBridge, NativeMemoryBackend
from .no_memory import NoMemoryBackend
from .openviking import OfflineOpenVikingClient, OpenVikingBackend, create_openviking_client
from .registry import create_memory_backend, register_memory_backend

__all__ = [
    "AgentNativeMemoryBridge",
    "HmArchBackend",
    "Mem0Backend",
    "NativeMemoryBackend",
    "NoMemoryBackend",
    "OfflineMem0Client",
    "OfflineOpenVikingClient",
    "OpenVikingBackend",
    "ProviderPackageRequired",
    "create_mem0_client",
    "create_memory_backend",
    "create_openviking_client",
    "register_memory_backend",
]
