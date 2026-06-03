"""Public package interface for the HM-Arch SDK."""

from ._version import __version__
from .config import MemoryConfig
from .context import AgentContext
from .core import HMArch
from .types import (
    ConsolidationReport,
    EventType,
    ForgetResult,
    MemoryItem,
    MemoryReceipt,
    MemoryStats,
    RetentionCurve,
    SearchResult,
)

__all__ = [
    "__version__",
    "HMArch",
    "AgentContext",
    "MemoryConfig",
    "EventType",
    "MemoryReceipt",
    "MemoryItem",
    "SearchResult",
    "ConsolidationReport",
    "RetentionCurve",
    "MemoryStats",
    "ForgetResult",
]
