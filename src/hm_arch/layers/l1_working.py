"""L1 Working Memory — bounded session item store.

Working memory holds a larger set of items accumulated during an agent session.
Like L0, it is purely in-memory and uses FIFO eviction: when the store is full,
the **oldest** item is silently dropped to make room for the new one.

Unlike L0's tiny sensory window, L1 is intended to hold a meaningful slice of
the current session—enough context to answer queries without hitting the slower
(and persisted) L2/L3 layers first.

Typical capacity: 50 items.
"""

from __future__ import annotations

from collections import deque
from typing import Deque

from .base import BaseLayer, LayerItem


__all__ = ["L1WorkingMemory"]

_DEFAULT_CAPACITY = 50


class L1WorkingMemory(BaseLayer):
    """Bounded in-memory working memory store (layer 1).

    Parameters
    ----------
    capacity:
        Maximum number of items to retain.  When a new item is added and the
        store is already at *capacity*, the oldest item is silently dropped.
        Defaults to ``50``.

    Examples
    --------
    ::

        wm = L1WorkingMemory(capacity=5)
        for i in range(6):
            wm.add(f"item {i}")
        # After 6 adds with capacity 5, "item 0" has been evicted.
        assert wm.size == 5
        contents = [item.content for item in wm.snapshot()]
        assert "item 0" not in contents
        assert "item 5" in contents
    """

    LAYER_INDEX = 1

    def __init__(self, capacity: int = _DEFAULT_CAPACITY) -> None:
        if capacity < 1:
            raise ValueError(f"capacity must be >= 1, got {capacity!r}")
        self._capacity = capacity
        self._store: Deque[LayerItem] = deque(maxlen=capacity)

    # ------------------------------------------------------------------
    # BaseLayer interface
    # ------------------------------------------------------------------

    def add(
        self,
        content: str,
        metadata: dict | None = None,
        *,
        memory_id: str | None = None,
    ) -> str:
        """Append *content* to working memory.

        If the store is already at :attr:`capacity`, the oldest item is
        automatically evicted by the underlying :class:`~collections.deque`.

        Parameters
        ----------
        content:
            Text to store.
        metadata:
            Optional key/value pairs attached to the item.
        memory_id:
            Optional durable L2 identifier to reuse so L1/L2 rows share the
            same ``memory_id`` (used by :class:`~hm_arch.core.HMArch.add`).

        Returns
        -------
        str
            The ``memory_id`` of the newly inserted item.
        """
        mid = memory_id if memory_id is not None else self._make_id()
        item = LayerItem(
            memory_id=mid,
            layer=self.LAYER_INDEX,
            content=content,
            added_at=self._now(),
            metadata=dict(metadata) if metadata is not None else {},
        )
        self._store.append(item)
        return mid

    def snapshot(self) -> list[LayerItem]:
        """Return all items ordered from **oldest to newest**.

        The returned list is a shallow copy of the internal store.
        """
        return list(self._store)

    def retrieve(self, query: str, top_k: int = 5) -> list[LayerItem]:
        """Return up to *top_k* items most relevant to *query*.

        Uses token-overlap scoring.  Items with equal relevance are returned
        most-recent first.
        """
        return self._score_items(query, list(self._store), top_k)

    def clear(self) -> None:
        """Remove all items from working memory."""
        self._store.clear()

    def load_snapshot(self, items: list[LayerItem]) -> None:
        """Replace working memory with a copy of *items* (oldest → newest).

        Used by :meth:`~hm_arch.core.HMArch.context` to restore session state
        after a scoped block.  Each item is shallow-copied so later mutations
        to the restored store do not affect the saved snapshot.
        """
        self._store.clear()
        for item in items:
            self._store.append(
                LayerItem(
                    memory_id=item.memory_id,
                    layer=item.layer,
                    content=item.content,
                    added_at=item.added_at,
                    metadata=dict(item.metadata),
                )
            )

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def capacity(self) -> int:
        """Maximum number of items the store holds before evicting."""
        return self._capacity

    @property
    def size(self) -> int:
        """Current number of items in the store."""
        return len(self._store)
