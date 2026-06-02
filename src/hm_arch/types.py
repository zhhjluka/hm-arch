"""Public dataclasses and enums for the HM-Arch SDK."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class EventType(str, Enum):
    """Supported event categories for memories added to HM-Arch."""

    CONVERSATION = "conversation"
    CODE_CHANGE = "code_change"
    COMMAND = "command"
    OBSERVATION = "observation"
    DECISION = "decision"
    DOCUMENT = "document"
    SYSTEM = "system"
    OTHER = "other"


@dataclass(slots=True)
class MemoryReceipt:
    """Acknowledgement returned when an event is accepted by memory."""

    memory_id: str
    layer: str
    event_type: EventType = EventType.OTHER
    timestamp: datetime = field(default_factory=_utc_now)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class MemoryItem:
    """A memory entry returned by storage, retrieval, or consolidation."""

    memory_id: str
    content: str
    layer: str
    event_type: EventType = EventType.OTHER
    created_at: datetime = field(default_factory=_utc_now)
    metadata: dict[str, Any] = field(default_factory=dict)
    retention: float = 1.0
    importance: float = 0.0


@dataclass(slots=True)
class SearchResult:
    """Ranked retrieval result with relevance, retention, and final score."""

    item: MemoryItem
    relevance: float
    retention: float
    score: float | None = None
    source_layer: str | None = None

    def __post_init__(self) -> None:
        if self.score is None:
            self.score = round(self.relevance * self.retention, 12)
        if self.source_layer is None:
            self.source_layer = self.item.layer


@dataclass(slots=True)
class ConsolidationReport:
    """Summary returned by a consolidation cycle."""

    episodes_processed: int = 0
    semantic_memories_created: int = 0
    semantic_memories_updated: int = 0
    memories_scheduled_for_review: int = 0
    memories_marked_deleted: int = 0


@dataclass(slots=True)
class RetentionCurve:
    """Retention forecast for a memory over elapsed days."""

    memory_id: str
    layer: str
    current_retention: float
    points: tuple[tuple[float, float], ...] = ()
    half_life_days: float | None = None


@dataclass(slots=True)
class MemoryStats:
    """Aggregate memory and storage counters."""

    total_memories: int = 0
    by_layer: dict[str, int] = field(default_factory=dict)
    storage_bytes: int = 0
    review_queue_size: int = 0
