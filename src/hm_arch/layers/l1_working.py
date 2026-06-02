"""L1 Working Memory — bounded session buffer, purely in-memory.

Working memory holds the agent's active short-term context for the
current session.  Like the sensory register it is entirely in-memory
with no persistence or decay, but it is larger and survives across
individual encode/retrieve calls within a single agent run.  When the
buffer is full the **oldest** entry is evicted to make room for the
newest one.
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

_DEFAULT_CAPACITY: int = 50
"""Default buffer size for working memory."""

_LAYER_PRIORITY: float = 0.9
"""Retrieval score multiplier for L1 (per PRD layer-priority table)."""


class L1WorkingMemory(MemoryLayer):
    """In-memory session buffer that retains recent working-memory items.

    Parameters
    ----------
    capacity:
        Maximum number of entries to retain.  Oldest entry is evicted
        when the limit is exceeded.  Must be at least 1.  Defaults to
        :data:`_DEFAULT_CAPACITY`.

    Raises
    ------
    ValueError
        When *capacity* is less than 1.

    Examples
    --------
    ::

        wm = L1WorkingMemory(capacity=3)
        wm.encode("task started")
        wm.encode("reading config")
        wm.encode("parsing source")
        wm.encode("linting file")   # evicts "task started"
        assert wm.size == 3
        contents = [e.content for e in wm.all_entries()]
        assert "task started" not in contents
        assert "linting file" in contents
    """

    def __init__(self, capacity: int = _DEFAULT_CAPACITY) -> None:
        if capacity < 1:
            raise ValueError(f"capacity must be >= 1, got {capacity!r}")
        self._capacity = capacity
        self._buffer: deque[LayerEntry] = deque(maxlen=capacity)

    # ------------------------------------------------------------------
    # MemoryLayer properties
    # ------------------------------------------------------------------

    @property
    def layer_index(self) -> int:
        return 1

    @property
    def capacity(self) -> int:
        return self._capacity

    @property
    def size(self) -> int:
        return len(self._buffer)

    # ------------------------------------------------------------------
    # MemoryLayer interface
    # ------------------------------------------------------------------

    def encode(
        self,
        content: str,
        event_type: EventType = EventType.OBSERVATION,
        metadata: Optional[dict] = None,
    ) -> str:
        """Append *content* to the working memory buffer.

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
        self._buffer.append(entry)
        return entry.entry_id

    def retrieve(self, query: str, top_k: int = 5) -> list[MemoryItem]:
        """Return up to *top_k* entries most relevant to *query*.

        Scoring: ``retention × relevance × layer_priority`` where
        ``layer_priority`` for L1 is :data:`_LAYER_PRIORITY` (``0.9``).
        Ties are broken by ``entry_id`` ascending for stable ordering.

        Parameters
        ----------
        query:
            Text to score against.
        top_k:
            Maximum number of results.

        Returns
        -------
        list[MemoryItem]
            Ranked list, highest combined score first.
        """
        query_tokens = _tokenize(query)
        entries = list(self._buffer)

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
        """Remove all entries from working memory."""
        self._buffer.clear()

    # ------------------------------------------------------------------
    # Convenience helpers
    # ------------------------------------------------------------------

    def all_entries(self) -> list[LayerEntry]:
        """Return all stored entries in insertion order (oldest first)."""
        return list(self._buffer)

    def __len__(self) -> int:
        return self.size

    def __repr__(self) -> str:
        return f"L1WorkingMemory(size={self.size}/{self.capacity})"
