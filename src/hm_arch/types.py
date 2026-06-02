"""Public data types for the HM-Arch SDK."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum


class EventType(str, Enum):
    """Classification of events stored in memory."""

    CONVERSATION = "conversation"
    CODE = "code"
    DECISION = "decision"
    TASK = "task"
    OBSERVATION = "observation"
    ERROR = "error"
    SYSTEM = "system"


@dataclass
class MemoryReceipt:
    """Confirmation returned by :py:meth:`HMArch.add`."""

    memory_id: str
    timestamp: datetime
    event_type: EventType
    layer: str
    content_preview: str


@dataclass
class MemoryItem:
    """A single memory record as returned from storage."""

    memory_id: str
    content: str
    event_type: EventType
    layer: str
    timestamp: datetime
    retention: float
    importance: float
    metadata: dict = field(default_factory=dict)


@dataclass
class SearchResult:
    """A single result returned by :py:meth:`HMArch.search`."""

    memory_id: str
    content: str
    score: float
    relevance: float
    retention: float
    layer: str
    event_type: EventType
    timestamp: datetime


@dataclass
class ConsolidationReport:
    """Summary returned by :py:meth:`HMArch.consolidate`."""

    consolidated_episodes: int
    semantic_triples_created: int
    semantic_triples_merged: int
    memories_scheduled_for_review: int
    duration_s: float
    timestamp: datetime


@dataclass
class RetentionCurve:
    """Predicted retention curve for a single memory."""

    memory_id: str
    layer: str
    timestamps_days: list[float]
    retention_values: list[float]
    half_life_days: float


@dataclass
class MemoryStats:
    """Aggregated statistics returned by :py:meth:`HMArch.get_stats`."""

    total_memories: int
    by_layer: dict[str, int]
    by_event_type: dict[str, int]
    db_size_bytes: int
    oldest_memory: datetime | None
    newest_memory: datetime | None
