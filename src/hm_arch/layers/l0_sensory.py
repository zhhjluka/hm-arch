"""L0 Sensory Register — bounded recent-event window.

The sensory register is the fastest and most transient layer.  It holds a
small, fixed-size window of the most recently added events.  When the window
is full, the **oldest** item is automatically evicted to make room for the new
one (FIFO eviction via :class:`collections.deque` with ``maxlen``).

This layer is entirely in-memory; it has no persistence and survives only for
the lifetime of the Python process (or until :meth:`L0SensoryRegister.clear`
is called).

Typical capacity: 7 items (human "magic number" sensory buffer).
"""

from __future__ import annotations

from collections import deque
from typing import Deque

from .base import BaseLayer, LayerItem


__all__ = ["L0SensoryRegister"]

_DEFAULT_CAPACITY = 7


class L0SensoryRegister(BaseLayer):
    """Bounded in-memory sensory register (layer 0).

    Parameters
    ----------
    capacity:
        Maximum number of items to retain.  When a new item is added and the
        register is already at *capacity*, the oldest item is silently dropped.
        Defaults to ``7``.

    Examples
    --------
    ::

        reg = L0SensoryRegister(capacity=3)
        reg.add("event one")
        reg.add("event two")
        reg.add("event three")
        # Adding a fourth item evicts "event one"
        reg.add("event four")
        assert reg.size == 3
        assert reg.snapshot()[0].content == "event two"
    """

    LAYER_INDEX = 0

    def __init__(self, capacity: int = _DEFAULT_CAPACITY) -> None:
        if capacity < 1:
            raise ValueError(f"capacity must be >= 1, got {capacity!r}")
        self._capacity = capacity
        self._window: Deque[LayerItem] = deque(maxlen=capacity)

    # ------------------------------------------------------------------
    # BaseLayer interface
    # ------------------------------------------------------------------

    def add(self, content: str, metadata: dict | None = None) -> str:
        """Append *content* to the sensory window.

        If the window is already at :attr:`capacity`, the oldest item is
        automatically evicted by the underlying :class:`~collections.deque`.

        Parameters
        ----------
        content:
            Text to store.
        metadata:
            Optional key/value pairs attached to the item.

        Returns
        -------
        str
            The ``memory_id`` of the newly inserted item.
        """
        mid = self._make_id()
        item = LayerItem(
            memory_id=mid,
            layer=self.LAYER_INDEX,
            content=content,
            added_at=self._now(),
            metadata=dict(metadata) if metadata is not None else {},
        )
        self._window.append(item)
        return mid

    def snapshot(self) -> list[LayerItem]:
        """Return all items ordered from **oldest to newest**.

        The returned list is a shallow copy of the internal window.
        """
        return list(self._window)

    def retrieve(self, query: str, top_k: int = 5) -> list[LayerItem]:
        """Return up to *top_k* items most relevant to *query*.

        Uses token-overlap scoring.  Items with equal relevance are returned
        most-recent first.
        """
        return self._score_items(query, list(self._window), top_k)

    def clear(self) -> None:
        """Remove all items from the sensory register."""
        self._window.clear()

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def capacity(self) -> int:
        """Maximum number of items the register holds before evicting."""
        return self._capacity

    @property
    def size(self) -> int:
        """Current number of items in the register."""
        return len(self._window)
