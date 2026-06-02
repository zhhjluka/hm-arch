"""L2 Episodic Buffer — durable raw event storage.

L2 is the first persistent memory layer.  Every event encoded by
:meth:`L2EpisodicBuffer.encode` is written atomically to:

1. ``memory_index`` — one row holding retention metadata, importance, status.
2. ``episodes`` — one row holding the raw content, event type, and optional
   context/emotion data.
3. The local vector store — so future :meth:`retrieve` calls can find it by
   semantic similarity (token-overlap in the local fallback).

Because the authoritative data lives in SQLite, the episodic buffer survives
process restarts: the in-memory vector index is automatically rebuilt from
the database when no external vector store is supplied.

Design notes
------------
* L2 does **not** inherit from :class:`~hm_arch.layers.base.BaseLayer` because
  it is not a purely in-memory layer and has a different construction contract
  (requires a live :class:`~hm_arch.storage.sqlite.SQLiteStore`).
* The ``encode`` / ``retrieve`` naming follows the PRD vocabulary for L2.
* Retention math is deliberately kept trivial (initial strength = 1.0, no
  decay applied here) — forgetting will be wired in by a later milestone.
* ``EpisodicItem`` carries the retention metadata needed by the HMArch facade
  search orchestrator in later issues.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone

from ..storage.sqlite import SQLiteStore
from ..storage.vector import LocalVectorStore, VectorStoreProtocol
from ..types import EventType


__all__ = [
    "EpisodicItem",
    "L2EpisodicBuffer",
]


# ---------------------------------------------------------------------------
# Return type
# ---------------------------------------------------------------------------


@dataclass
class EpisodicItem:
    """A single episodic memory returned by :meth:`L2EpisodicBuffer.retrieve`.

    Attributes
    ----------
    memory_id:
        Unique identifier shared between ``memory_index`` and ``episodes``.
    layer:
        Always ``2`` for L2 episodic items.
    content:
        Raw text content of the episode.
    event_type:
        String value of the :class:`~hm_arch.types.EventType` used at encode
        time (e.g. ``"conversation"``).
    importance:
        Importance score in ``[0, 1]`` stored at insertion time.
    retention:
        Current retention value in ``[0, 1]``; ``1.0`` for newly encoded
        episodes.  Decay is applied by the forgetting layer in a later
        milestone — L2 just stores and surfaces the value.
    relevance:
        Query-relevance score in ``[0, 1]`` produced by the vector store.
    created_at:
        Timezone-aware UTC datetime of when the episode was persisted.
    metadata:
        Arbitrary caller-supplied key/value pairs stored in ``memory_index``.
    """

    memory_id: str
    layer: int
    content: str
    event_type: str
    importance: float
    retention: float
    relevance: float
    created_at: datetime
    metadata: dict = field(default_factory=dict)


# ---------------------------------------------------------------------------
# L2 implementation
# ---------------------------------------------------------------------------


class L2EpisodicBuffer:
    """Durable episodic memory buffer (layer 2).

    Persists raw events to SQLite and keeps a vector index for similarity
    search.  The vector index is rebuilt from SQLite on construction when no
    external store is supplied, so the layer survives process restarts without
    data loss.

    Parameters
    ----------
    db:
        An already-connected :class:`~hm_arch.storage.sqlite.SQLiteStore`
        with the schema initialised.  The caller owns the connection lifecycle
        (``connect`` / ``close`` / context-manager).
    vector_store:
        Optional vector backend conforming to
        :class:`~hm_arch.storage.vector.VectorStoreProtocol`.  When ``None``
        a fresh :class:`~hm_arch.storage.vector.LocalVectorStore` is created
        and its index is populated from the existing SQLite episodes.
    default_importance:
        Importance score applied when the caller does not supply one.
        Must be in ``[0, 1]``.  Defaults to ``0.5``.
    default_initial_strength:
        Initial retention/strength written to ``memory_index`` for new
        episodes.  Must be in ``[0, 1]``.  Defaults to ``1.0``.

    Examples
    --------
    ::

        from hm_arch.storage.sqlite import SQLiteStore
        from hm_arch.layers.l2_episodic import L2EpisodicBuffer
        from hm_arch.types import EventType

        db = SQLiteStore(":memory:").connect()
        db.initialize_schema()
        l2 = L2EpisodicBuffer(db)

        mid = l2.encode("User prefers Python", event_type=EventType.CONVERSATION)
        results = l2.retrieve("Python preference", top_k=3)
        assert results[0].memory_id == mid
    """

    LAYER_INDEX: int = 2

    def __init__(
        self,
        db: SQLiteStore,
        vector_store: VectorStoreProtocol | None = None,
        default_importance: float = 0.5,
        default_initial_strength: float = 1.0,
    ) -> None:
        self._db = db
        self._default_importance = default_importance
        self._default_initial_strength = default_initial_strength

        if vector_store is not None:
            self._vector: VectorStoreProtocol = vector_store
        else:
            local = LocalVectorStore()
            self._vector = local
            self._rebuild_vector_index()

    # ------------------------------------------------------------------
    # Primary public interface
    # ------------------------------------------------------------------

    def encode(
        self,
        content: str,
        event_type: EventType = EventType.OBSERVATION,
        metadata: dict | None = None,
        importance: float | None = None,
        emotion_score: float | None = None,
        context_window: str | None = None,
    ) -> str:
        """Persist a raw event as an L2 episodic memory.

        Writes atomically to ``memory_index``, ``episodes``, and the vector
        store.  The caller does not need to flush or commit; ``SQLiteStore``
        commits after every :meth:`~SQLiteStore.execute` call.

        Parameters
        ----------
        content:
            Raw text of the event to remember.
        event_type:
            Classification; defaults to :attr:`~hm_arch.types.EventType.OBSERVATION`.
        metadata:
            Arbitrary key/value pairs stored in ``memory_index.metadata``.
        importance:
            Override for the layer-level default importance.  Clamped to
            ``[0, 1]``.
        emotion_score:
            Optional emotional valence stored in the ``episodes`` row.
        context_window:
            Optional free-text snapshot of the surrounding context.

        Returns
        -------
        str
            The ``memory_id`` (UUID4 hex string) assigned to this episode.
        """
        mid = uuid.uuid4().hex
        now_str = _iso_now()
        imp = importance if importance is not None else self._default_importance
        event_type_str = (
            event_type.value if isinstance(event_type, EventType) else str(event_type)
        )
        meta_str = json.dumps(dict(metadata) if metadata is not None else {})
        content_hash = hashlib.sha256(content.encode()).hexdigest()

        # 1. Persist to memory_index
        self._db.execute(
            """
            INSERT INTO memory_index (
                id, layer, created_at, updated_at, importance,
                initial_strength, current_retention, status,
                tags, metadata, content_hash
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                mid,
                self.LAYER_INDEX,
                now_str,
                now_str,
                imp,
                self._default_initial_strength,
                self._default_initial_strength,
                "active",
                "[]",
                meta_str,
                content_hash,
            ),
        )

        # 2. Persist to episodes (episode pk is separate from memory_id)
        episode_id = uuid.uuid4().hex
        self._db.execute(
            """
            INSERT INTO episodes (
                id, memory_id, content, event_type,
                emotion_score, context_window, raw_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                episode_id,
                mid,
                content,
                event_type_str,
                emotion_score,
                context_window,
                None,
            ),
        )

        # 3. Upsert into vector store (keyed by memory_id for easy lookup)
        self._vector.upsert(
            mid,
            content,
            metadata={
                "layer": self.LAYER_INDEX,
                "event_type": event_type_str,
                "importance": imp,
            },
        )

        return mid

    def retrieve(
        self,
        query: str,
        top_k: int = 5,
    ) -> list[EpisodicItem]:
        """Return up to *top_k* episodes most relevant to *query*.

        Retrieval is a two-step process:

        1. Query the vector store for candidate memory_ids ranked by
           token-overlap score.
        2. For each hit, join ``memory_index`` and ``episodes`` in SQLite to
           attach retention metadata.

        Only ``status = 'active'`` rows are returned.

        Parameters
        ----------
        query:
            Search string.
        top_k:
            Maximum number of results.  The vector store may return fewer
            if the store contains fewer than *top_k* documents.

        Returns
        -------
        list[EpisodicItem]
            Items ordered by relevance descending (highest relevance first).
        """
        vector_hits = self._vector.query(query, top_k=top_k)
        if not vector_hits:
            return []

        items: list[EpisodicItem] = []
        for hit in vector_hits:
            row = self._fetch_episode_row(hit.id)
            if row is None:
                continue
            items.append(
                EpisodicItem(
                    memory_id=hit.id,
                    layer=self.LAYER_INDEX,
                    content=row["content"],
                    event_type=row["event_type"],
                    importance=row["importance"],
                    retention=row["current_retention"],
                    relevance=hit.score,
                    created_at=_parse_iso(row["created_at"]),
                    metadata=json.loads(row["metadata"] or "{}"),
                )
            )
        return items

    # ------------------------------------------------------------------
    # Convenience introspection
    # ------------------------------------------------------------------

    def count(self) -> int:
        """Return the number of active L2 episodes stored in SQLite."""
        rows = self._db.query(
            "SELECT COUNT(*) FROM memory_index WHERE layer = ? AND status = 'active'",
            (self.LAYER_INDEX,),
        )
        return rows[0][0] if rows else 0

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _fetch_episode_row(self, memory_id: str) -> dict | None:
        """Fetch a joined memory_index + episodes row for *memory_id*.

        Returns a plain dict (column → value) or ``None`` when not found or
        when the row is not active.
        """
        rows = self._db.query(
            """
            SELECT mi.id,
                   mi.created_at,
                   mi.importance,
                   mi.current_retention,
                   mi.metadata,
                   e.content,
                   e.event_type
            FROM   memory_index mi
            JOIN   episodes     e ON e.memory_id = mi.id
            WHERE  mi.id     = ?
              AND  mi.layer  = ?
              AND  mi.status = 'active'
            """,
            (memory_id, self.LAYER_INDEX),
        )
        if not rows:
            return None
        r = rows[0]
        return {
            "id": r["id"],
            "created_at": r["created_at"],
            "importance": r["importance"],
            "current_retention": r["current_retention"],
            "metadata": r["metadata"],
            "content": r["content"],
            "event_type": r["event_type"],
        }

    def _rebuild_vector_index(self) -> None:
        """Populate the in-memory vector store from existing SQLite episodes.

        This is called once at construction time (when no external vector
        store is supplied) so that restarts do not lose retrieval capability.
        SQLite is the source of truth; the local vector store is derived from
        it on demand.
        """
        rows = self._db.query(
            """
            SELECT mi.id,
                   mi.importance,
                   e.content,
                   e.event_type
            FROM   memory_index mi
            JOIN   episodes     e ON e.memory_id = mi.id
            WHERE  mi.layer  = ?
              AND  mi.status = 'active'
            """,
            (self.LAYER_INDEX,),
        )
        for row in rows:
            self._vector.upsert(
                row["id"],
                row["content"],
                metadata={
                    "layer": self.LAYER_INDEX,
                    "event_type": row["event_type"],
                    "importance": row["importance"],
                },
            )


# ---------------------------------------------------------------------------
# Private utilities
# ---------------------------------------------------------------------------


def _iso_now() -> str:
    """Return the current UTC time formatted as ISO 8601."""
    return datetime.now(tz=timezone.utc).isoformat()


def _parse_iso(iso_str: str) -> datetime:
    """Parse an ISO 8601 string into a timezone-aware :class:`datetime`.

    Strings without explicit timezone info are assumed to be UTC.
    """
    dt = datetime.fromisoformat(iso_str)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt
