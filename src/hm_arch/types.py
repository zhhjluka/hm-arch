"""Public data types for the HM-Arch SDK.

All shapes here mirror the PRD API contract. Later implementation modules
(storage, layers, forgetting) must conform to these signatures.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum


class EventType(str, Enum):
    """Classification of events stored in memory."""

    CONVERSATION = "conversation"
    OBSERVATION = "observation"
    DECISION = "decision"
    ERROR = "error"
    CODE = "code"
    TASK = "task"
    SYSTEM = "system"


@dataclass
class MemoryReceipt:
    """Confirmation returned by :py:meth:`HMArch.add`.

    Attributes
    ----------
    memory_id:
        Unique identifier for the persisted memory.
    layer:
        Integer layer index where the memory was stored (0=L0 … 3=L3).
    importance:
        Computed importance score in ``[0, 1]``.
    initial_strength:
        Initial memory strength (retention) at insertion time.
    decay_estimate:
        Predicted retention at key future checkpoints, e.g.
        ``{"1d": 0.92, "7d": 0.65, "30d": 0.28}``.
    consolidation_scheduled:
        When the memory is next scheduled for consolidation review.
    """

    memory_id: str
    layer: int
    importance: float
    initial_strength: float
    decay_estimate: dict
    consolidation_scheduled: datetime


@dataclass
class MemoryItem:
    """A single memory record returned inside a :class:`SearchResult`.

    Attributes
    ----------
    memory_id:
        Unique identifier.
    layer:
        Integer layer index (0–3).
    content:
        Raw text content of the memory.
    retention:
        Current retention value in ``[0, 1]``.
    relevance:
        Query-relevance score in ``[0, 1]``.
    score:
        Combined ranking score (``retention * relevance * layer_priority``).
    metadata:
        Arbitrary extra fields stored alongside the memory.
    """

    memory_id: str
    layer: int
    content: str
    retention: float
    relevance: float
    score: float
    metadata: dict = field(default_factory=dict)


@dataclass
class SearchResult:
    """Wrapper returned by :py:meth:`HMArch.search`.

    Individual hits are carried in :attr:`results` as :class:`MemoryItem`
    objects.  The wrapper also exposes diagnostic metadata about the search
    itself.

    Attributes
    ----------
    results:
        Ranked list of matching memory items.
    total_scanned:
        Total number of candidates examined before scoring.
    timing_ms:
        Wall-clock time spent on the search in milliseconds.
    source_breakdown:
        Number of candidates considered per layer, keyed by integer layer
        index, e.g. ``{0: 5, 1: 12, 2: 40, 3: 8}``.
    """

    results: list[MemoryItem]
    total_scanned: int
    timing_ms: float
    source_breakdown: dict[int, int]


@dataclass
class ConsolidationReport:
    """Summary returned by :py:meth:`HMArch.consolidate`.

    Attributes
    ----------
    extracted_semantics:
        Number of semantic triples extracted from episodic memories.
    merged_duplicates:
        Number of duplicate entries merged during the cycle.
    resolved_conflicts:
        Number of conflicting semantic facts superseded.
    archived_to_l4:
        Number of memories promoted to the L4 compressed archive.
    scheduled_reviews:
        Number of memories added to the review queue.
    marked_deletable:
        Number of memories flagged for future physical deletion.
    duration_seconds:
        Wall-clock time taken for the consolidation cycle.
    """

    extracted_semantics: int
    merged_duplicates: int
    resolved_conflicts: int
    archived_to_l4: int
    scheduled_reviews: int
    marked_deletable: int
    duration_seconds: float


@dataclass
class RetentionCurve:
    """Predicted retention curve returned by :py:meth:`HMArch.get_retention_curve`.

    Attributes
    ----------
    days:
        Sorted list of day offsets at which retention was sampled.
    retention:
        Retention values (in ``[0, 1]``) corresponding to each day in
        :attr:`days`.
    review_suggested_at_day:
        Earliest day at which a review is recommended to maintain retention.
    archive_at_day:
        Day at which retention drops below the archive threshold.
    """

    days: list[int]
    retention: list[float]
    review_suggested_at_day: int
    archive_at_day: int


@dataclass
class MemoryStats:
    """Aggregated statistics returned by :py:meth:`HMArch.get_stats`.

    Attributes
    ----------
    total_memories:
        Total number of active memories across all layers.
    by_layer:
        Per-layer counts keyed by integer layer index.
    storage_size_mb:
        On-disk storage used by the database in megabytes.
    retention_distribution:
        Histogram or summary of current retention values, e.g.
        ``{"0-0.25": 12, "0.25-0.5": 30, "0.5-0.75": 45, "0.75-1.0": 60}``.
    review_queue_length:
        Number of memories currently scheduled for review.
    last_consolidation_at:
        Timestamp of the most recent consolidation cycle, or ``None`` if
        consolidation has not yet run.
    archive_storage_mb:
        On-disk size of L4 gzip archives under the archive root, in megabytes.
    """

    total_memories: int
    by_layer: dict[int, int]
    storage_size_mb: float
    retention_distribution: dict
    review_queue_length: int
    last_consolidation_at: datetime | None
    archive_storage_mb: float = 0.0


@dataclass
class ForgetResult:
    """Result returned by :py:meth:`HMArch.forget`.

    Attributes
    ----------
    forgotten_count:
        Number of memories removed or marked deleted.
    archived_count:
        Number of memories moved to the L4 archive instead of deleted.
    freed_memory_mb:
        Approximate storage freed in megabytes.
    affected_layers:
        List of integer layer indices from which memories were removed.
    details:
        Per-memory detail records, each a dict with at least ``memory_id``
        and ``action`` (``"deleted"`` | ``"archived"``).
    """

    forgotten_count: int
    archived_count: int
    freed_memory_mb: float
    affected_layers: list[int]
    details: list[dict]
