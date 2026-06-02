"""Base abstraction for in-memory HM-Arch layers.

Defines :class:`LayerItem` (the unit stored in L0/L1) and
:class:`BaseLayer` (the abstract base every in-memory layer must implement).

Design notes
------------
* Both L0 and L1 are purely in-memory with no persistence requirement.
* Each layer is responsible for its own bounded eviction; callers should not
  need to know about the eviction strategy.
* The ``retrieve`` method uses the same token-overlap scoring algorithm as
  :class:`~hm_arch.storage.vector.LocalVectorStore` so results are
  deterministic and require no external dependencies.
* :class:`BaseLayer` uses ``ABC`` / ``abstractmethod`` rather than a
  ``Protocol`` because concrete subclasses share helper logic (e.g.
  ``_score_items``).
"""

from __future__ import annotations

import re
import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Sequence


__all__ = [
    "LayerItem",
    "BaseLayer",
]


# ---------------------------------------------------------------------------
# Data type stored in every layer
# ---------------------------------------------------------------------------


@dataclass
class LayerItem:
    """A single entry held inside an in-memory layer (L0 or L1).

    Attributes
    ----------
    memory_id:
        Globally unique identifier assigned at insertion time.
    layer:
        Integer layer index (0 for L0, 1 for L1).
    content:
        Raw text content of the memory.
    added_at:
        UTC timestamp of when the item was added to the layer.
    metadata:
        Arbitrary caller-supplied key/value pairs.
    """

    memory_id: str
    layer: int
    content: str
    added_at: datetime
    metadata: dict = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Token-overlap scoring (stdlib-only, identical to LocalVectorStore logic)
# ---------------------------------------------------------------------------

_TOKEN_RE = re.compile(r"[a-z0-9]+|[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]")


def _tokenize(text: str) -> list[str]:
    return _TOKEN_RE.findall(text.lower())


def _token_overlap_score(query_tokens: list[str], doc_tokens: list[str]) -> float:
    """Deterministic relevance via token-frequency overlap.

    Returns a value in ``[0.0, 1.0]``.  Returns ``0.0`` when either list is
    empty.
    """
    if not query_tokens or not doc_tokens:
        return 0.0

    query_tf: dict[str, int] = {}
    for t in query_tokens:
        query_tf[t] = query_tf.get(t, 0) + 1

    doc_tf: dict[str, int] = {}
    for t in doc_tokens:
        doc_tf[t] = doc_tf.get(t, 0) + 1

    overlap = sum(min(cnt, doc_tf.get(tok, 0)) for tok, cnt in query_tf.items())
    denom = max(len(query_tokens), len(doc_tokens))
    return overlap / denom


# ---------------------------------------------------------------------------
# Abstract base layer
# ---------------------------------------------------------------------------


class BaseLayer(ABC):
    """Abstract base class for bounded in-memory layers (L0, L1).

    Subclasses must implement :meth:`add`, :meth:`snapshot`, :meth:`retrieve`,
    and :meth:`clear`.  They must also set :attr:`LAYER_INDEX` as a class-level
    constant.

    Helper utilities available to subclasses:

    * :meth:`_make_id` — generate a new unique ``memory_id``.
    * :meth:`_now` — return current UTC time.
    * :meth:`_score_items` — rank a sequence of :class:`LayerItem` objects
      against a query string using token-overlap scoring.
    """

    #: Concrete subclasses must override this with their integer layer index.
    LAYER_INDEX: int = -1

    # ------------------------------------------------------------------
    # Abstract interface
    # ------------------------------------------------------------------

    @abstractmethod
    def add(self, content: str, metadata: dict | None = None) -> str:
        """Add *content* to the layer and return the assigned ``memory_id``.

        When the layer is at capacity the **oldest** entry is silently evicted
        before the new item is inserted.

        Parameters
        ----------
        content:
            Text to store.
        metadata:
            Optional caller-supplied key/value pairs attached to the item.

        Returns
        -------
        str
            The ``memory_id`` of the newly added item.
        """

    @abstractmethod
    def snapshot(self) -> list[LayerItem]:
        """Return all current items ordered from **oldest to newest**.

        The returned list is a shallow copy; mutating it does not affect the
        layer's internal state.
        """

    @abstractmethod
    def retrieve(self, query: str, top_k: int = 5) -> list[LayerItem]:
        """Return up to *top_k* items most relevant to *query*.

        Relevance is measured via token-overlap scoring.  Ties are broken by
        insertion order (most recent first) so that results are stable and
        deterministic.

        Parameters
        ----------
        query:
            The search string.
        top_k:
            Maximum number of items to return.
        """

    @abstractmethod
    def clear(self) -> None:
        """Remove all items from the layer."""

    # ------------------------------------------------------------------
    # Read-only properties
    # ------------------------------------------------------------------

    @property
    @abstractmethod
    def capacity(self) -> int:
        """Maximum number of items the layer can hold before evicting."""

    @property
    @abstractmethod
    def size(self) -> int:
        """Current number of items stored in the layer."""

    # ------------------------------------------------------------------
    # Protected helpers available to subclasses
    # ------------------------------------------------------------------

    @staticmethod
    def _make_id() -> str:
        """Return a new unique ``memory_id`` (UUID4 hex string)."""
        return uuid.uuid4().hex

    @staticmethod
    def _now() -> datetime:
        """Return the current UTC time (timezone-aware)."""
        return datetime.now(tz=timezone.utc)

    @staticmethod
    def _score_items(
        query: str,
        items: Sequence[LayerItem],
        top_k: int,
    ) -> list[LayerItem]:
        """Rank *items* against *query* and return at most *top_k* results.

        Sorting keys (in order):
        1. Score descending (higher relevance first).
        2. ``added_at`` descending (more recent first, as tiebreak).
        3. ``memory_id`` ascending (fully deterministic final tiebreak).
        """
        query_tokens = _tokenize(query)
        scored: list[tuple[float, LayerItem]] = [
            (_token_overlap_score(query_tokens, _tokenize(item.content)), item)
            for item in items
        ]
        scored.sort(key=lambda x: (-x[0], -x[1].added_at.timestamp(), x[1].memory_id))
        return [item for _, item in scored[:top_k]]
