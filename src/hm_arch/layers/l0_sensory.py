"""L0 Sensory Register — bounded sliding window, purely in-memory.

The sensory register models the very first stage of human memory: raw,
transient perception.  It keeps only the most recent *N* events.  When
the window is full the **oldest** entry is automatically evicted as the
new one arrives.  There is no persistence and no decay; entries are
either present or gone.
"""

from __future__ import annotations

from collections import deque
from typing import Optional

from hm_arch.layers.base import (
    LayerEntry,
    MemoryLayer,
    _token_overlap_score,
    _tokenize,
)
from hm_arch.types import EventType, MemoryItem

_DEFAULT_CAPACITY: int = 20
"""Default window size for the sensory register."""

_LAYER_PRIORITY: float = 1.0
"""Retrieval score multiplier for L0 (highest priority layer)."""


class L0SensoryRegister(MemoryLayer):
    """In-memory sliding window that retains the most recent inputs.

    Parameters
    ----------
    capacity:
        Maximum number of entries to keep.  Once this limit is reached
        the oldest entry is evicted before each new insertion.  Must be
        at least 1.  Defaults to :data:`_DEFAULT_CAPACITY`.

    Raises
    ------
    ValueError
        When *capacity* is less than 1.

    Examples
    --------
    ::

        register = L0SensoryRegister(capacity=5)
        for i in range(6):
            register.encode(f"event {i}")
        assert register.size == 5
        contents = [e.content for e in register.all_entries()]
        assert "event 0" not in contents  # oldest was evicted
        assert "event 5" in contents
    """

    def __init__(self, capacity: int = _DEFAULT_CAPACITY) -> None:
        if capacity < 1:
            raise ValueError(f"capacity must be >= 1, got {capacity!r}")
        self._capacity = capacity
        # Python's deque with maxlen provides automatic FIFO eviction.
        self._window: deque[LayerEntry] = deque(maxlen=capacity)

    # ------------------------------------------------------------------
    # MemoryLayer properties
    # ------------------------------------------------------------------

    @property
    def layer_index(self) -> int:
        return 0

    @property
    def capacity(self) -> int:
        return self._capacity

    @property
    def size(self) -> int:
        return len(self._window)

    # ------------------------------------------------------------------
    # MemoryLayer interface
    # ------------------------------------------------------------------

    def encode(
        self,
        content: str,
        event_type: EventType = EventType.OBSERVATION,
        metadata: Optional[dict] = None,
    ) -> str:
        """Append *content* to the window, evicting the oldest if full.

        Parameters
        ----------
        content:
            Text of the new memory.
        event_type:
            Event classification; defaults to
            :attr:`~hm_arch.types.EventType.OBSERVATION`.
        metadata:
            Optional arbitrary key/value pairs stored with the entry.

        Returns
        -------
        str
            The ``entry_id`` of the newly created :class:`.LayerEntry`.
        """
        entry = LayerEntry.new(content, event_type, metadata)
        self._window.append(entry)  # deque maxlen handles eviction
        return entry.entry_id

    def retrieve(self, query: str, top_k: int = 5) -> list[MemoryItem]:
        """Return up to *top_k* entries most relevant to *query*.

        Scoring: ``retention × relevance × layer_priority`` where
        ``layer_priority`` for L0 is :data:`_LAYER_PRIORITY` (``1.0``).
        Ties are broken by ``entry_id`` ascending for stable ordering.

        Parameters
        ----------
        query:
            Text to score against.
        top_k:
            Maximum number of results; returns fewer when the window
            contains fewer items.

        Returns
        -------
        list[MemoryItem]
            Ranked list, highest combined score first.
        """
        query_tokens = _tokenize(query)
        entries = list(self._window)

        # (score, entry_id, relevance, entry) — entry_id is the tiebreak key
        scored: list[tuple[float, str, float, LayerEntry]] = []
        for entry in entries:
            doc_tokens = _tokenize(entry.content)
            relevance = _token_overlap_score(query_tokens, doc_tokens)
            score = entry.retention * relevance * _LAYER_PRIORITY
            scored.append((score, entry.entry_id, relevance, entry))

        scored.sort(key=lambda x: (-x[0], x[1]))

        return [
            MemoryItem(
                memory_id=e.entry_id,
                layer=self.layer_index,
                content=e.content,
                retention=e.retention,
                relevance=rel,
                score=sc,
                metadata=dict(e.metadata),
            )
            for sc, _, rel, e in scored[:top_k]
        ]

    def clear(self) -> None:
        """Remove all entries from the sensory register."""
        self._window.clear()

    # ------------------------------------------------------------------
    # Convenience helpers
    # ------------------------------------------------------------------

    def all_entries(self) -> list[LayerEntry]:
        """Return all stored entries in insertion order (oldest first)."""
        return list(self._window)

    def __len__(self) -> int:
        return self.size

    def __repr__(self) -> str:
        return f"L0SensoryRegister(size={self.size}/{self.capacity})"
