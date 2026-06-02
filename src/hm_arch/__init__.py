"""Public package interface for the HM-Arch SDK."""

from ._version import __version__
from .config import MemoryConfig
from .types import (
    ConsolidationReport,
    EventType,
    MemoryItem,
    MemoryReceipt,
    MemoryStats,
    RetentionCurve,
    SearchResult,
)

__all__ = [
    "__version__",
    "ConsolidationReport",
    "EventType",
    "MemoryConfig",
    "MemoryItem",
    "MemoryReceipt",
    "MemoryStats",
    "RetentionCurve",
    "SearchResult",
]
