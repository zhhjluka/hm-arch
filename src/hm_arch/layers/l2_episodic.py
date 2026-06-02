"""L2 Episodic Buffer — durable episodic memory backed by SQLite and a vector store.

Unlike L0 and L1 (which are purely in-memory), L2 persists every encoded event
to SQLite so that memory survives process restarts.  A vector store (default:
:class:`~hm_arch.storage.vector.LocalVectorStore`) provides fast similarity
search; it is hydrated from the SQLite ``episodes`` / ``memory_index`` tables
on construction so that restarts preserve full retrieval capability.

Design notes
------------
* Two tables are written on encode: ``memory_index`` (one row per memory,
  shared across layers) and ``episodes`` (L2-specific fields: content,
  event_type, etc.).
* The vector store is an in-process index.  Because ``LocalVectorStore`` is
  purely in-memory it is repopulated from SQLite on each
  :class:`L2EpisodicBuffer` construction — no extra persistence step needed.
* :meth:`retrieve` returns :class:`~hm_arch.layers.base.LayerItem` objects,
  consistent with the L0/L1 interface, with retention and event-type metadata
  folded into the ``metadata`` dict.
* :meth:`clear` performs a **soft delete** (sets ``status='deleted'`` in
  ``memory_index``) so that data can be inspected for audit; physical rows
  remain until a future vacuum step.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone

from ..storage.sqlite import SQLiteStore
from ..storage.vector import LocalVectorStore, VectorStoreProtocol
from ..types import EventType
from .base import LayerItem

__all__ = ["L2EpisodicBuffer"]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _now_iso() -> str:
    """Return the current UTC time as an ISO 8601 string."""
    return datetime.now(tz=timezone.utc).isoformat()


def _parse_dt(s: str) -> datetime:
    """Parse an ISO 8601 string into a timezone-aware :class:`datetime`."""
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


# ---------------------------------------------------------------------------
# L2EpisodicBuffer
# ---------------------------------------------------------------------------


class L2EpisodicBuffer:
    """Durable episodic memory buffer (layer 2).

    Encodes raw events into SQLite (``episodes`` + ``memory_index``) and
    upserts their text into a vector store for fast similarity search.

    Parameters
    ----------
    sqlite_store:
        An already-connected :class:`~hm_arch.storage.sqlite.SQLiteStore`
        with the schema initialized.
    vector_store:
        Any object satisfying
        :class:`~hm_arch.storage.vector.VectorStoreProtocol`.  Defaults to a
        fresh :class:`~hm_arch.storage.vector.LocalVectorStore`.

    Examples
    --------
    ::

        from hm_arch.storage.sqlite import SQLiteStore
        from hm_arch.layers.l2_episodic import L2EpisodicBuffer
        from hm_arch.types import EventType

        store = SQLiteStore(":memory:")
        store.connect()
        store.initialize_schema()

        l2 = L2EpisodicBuffer(store)
        mid = l2.encode("The user prefers Python", event_type=EventType.CONVERSATION)
        results = l2.retrieve("Python preference")
        assert results[0].memory_id == mid
    """

    LAYER_INDEX: int = 2

    def __init__(
        self,
        sqlite_store: SQLiteStore,
        vector_store: VectorStoreProtocol | None = None,
    ) -> None:
        self._db = sqlite_store
        self._vector: VectorStoreProtocol = (
            vector_store if vector_store is not None else LocalVectorStore()
        )
        self._hydrate_from_db()

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def encode(
        self,
        content: str,
        event_type: EventType | str = EventType.OBSERVATION,
        metadata: dict | None = None,
        importance: float = 0.5,
        initial_strength: float = 0.5,
    ) -> str:
        """Persist an episode to SQLite and upsert into the vector store.

        Writes one row to ``memory_index`` (shared index for all layers) and
        one row to ``episodes`` (L2-specific table).  Also upserts the content
        into the configured vector store under the same ``memory_id``.

        Parameters
        ----------
        content:
            Raw text content of the event.
        event_type:
            Classification of the event.  Accepts an
            :class:`~hm_arch.types.EventType` enum value or a plain string.
        metadata:
            Optional caller-supplied key/value pairs stored in
            ``memory_index.metadata`` (serialised as JSON).
        importance:
            Importance score in ``[0, 1]`` written to ``memory_index``.
        initial_strength:
            Initial retention strength in ``[0, 1]``.

        Returns
        -------
        str
            The ``memory_id`` assigned to the new episode.
        """
        mid = uuid.uuid4().hex
        ep_id = uuid.uuid4().hex
        now = _now_iso()
        event_type_str = (
            event_type.value if isinstance(event_type, EventType) else str(event_type)
        )
        meta_json = json.dumps(dict(metadata) if metadata else {})

        self._db.execute(
            """INSERT INTO memory_index
               (id, layer, created_at, updated_at, importance, initial_strength,
                current_retention, status, tags, metadata)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                mid,
                self.LAYER_INDEX,
                now,
                now,
                importance,
                initial_strength,
                1.0,
                "active",
                "[]",
                meta_json,
            ),
        )
        self._db.execute(
            "INSERT INTO episodes (id, memory_id, content, event_type) VALUES (?, ?, ?, ?)",
            (ep_id, mid, content, event_type_str),
        )
        self._vector.upsert(
            mid,
            content,
            metadata={
                "layer": self.LAYER_INDEX,
                "event_type": event_type_str,
                "importance": importance,
            },
        )
        return mid

    def retrieve(
        self,
        query: str,
        top_k: int = 10,
    ) -> list[LayerItem]:
        """Return up to *top_k* episodes most relevant to *query*.

        Searches the vector store for candidate ``memory_id`` values, then
        enriches each hit with retention metadata fetched from
        ``memory_index`` and ``episodes``.  Episodes with
        ``status != 'active'`` are silently excluded.

        Parameters
        ----------
        query:
            The search string.
        top_k:
            Maximum number of results to return.

        Returns
        -------
        list[LayerItem]
            Results ordered by vector-store relevance score descending.
            Each item's ``metadata`` dict contains:

            * ``retention`` — current retention from ``memory_index``.
            * ``importance`` — importance score.
            * ``event_type`` — string event-type tag from ``episodes``.
            * ``relevance`` — vector-store score in ``[0, 1]``.
        """
        hits = self._vector.query(query, top_k=top_k)
        results: list[LayerItem] = []
        for hit in hits:
            rows = self._db.query(
                """SELECT mi.current_retention, mi.importance, mi.created_at,
                          e.content, e.event_type
                   FROM memory_index mi
                   JOIN episodes e ON e.memory_id = mi.id
                   WHERE mi.id = ? AND mi.layer = ? AND mi.status = 'active'""",
                (hit.id, self.LAYER_INDEX),
            )
            if not rows:
                continue
            row = rows[0]
            results.append(
                LayerItem(
                    memory_id=hit.id,
                    layer=self.LAYER_INDEX,
                    content=row["content"],
                    added_at=_parse_dt(row["created_at"]),
                    metadata={
                        "retention": row["current_retention"],
                        "importance": row["importance"],
                        "event_type": row["event_type"],
                        "relevance": hit.score,
                    },
                )
            )
        return results

    def snapshot(self, limit: int | None = None) -> list[LayerItem]:
        """Return active episodes ordered **oldest to newest**.

        Parameters
        ----------
        limit:
            Maximum number of items to return.  ``None`` means no limit.

        Returns
        -------
        list[LayerItem]
            Active items ordered by ``memory_index.created_at`` ascending.
            Each item's ``metadata`` dict contains ``retention``,
            ``importance``, and ``event_type``.
        """
        sql = """
            SELECT mi.id, mi.current_retention, mi.importance, mi.created_at,
                   e.content, e.event_type
            FROM memory_index mi
            JOIN episodes e ON e.memory_id = mi.id
            WHERE mi.layer = ? AND mi.status = 'active'
            ORDER BY mi.created_at ASC
        """
        params: tuple = (self.LAYER_INDEX,)
        if limit is not None:
            sql = sql.rstrip() + "\n            LIMIT ?"
            params = (self.LAYER_INDEX, limit)
        rows = self._db.query(sql, params)
        return [
            LayerItem(
                memory_id=row["id"],
                layer=self.LAYER_INDEX,
                content=row["content"],
                added_at=_parse_dt(row["created_at"]),
                metadata={
                    "retention": row["current_retention"],
                    "importance": row["importance"],
                    "event_type": row["event_type"],
                },
            )
            for row in rows
        ]

    def clear(self) -> None:
        """Soft-delete all active L2 episodes.

        Sets ``status = 'deleted'`` in ``memory_index`` for every active L2
        row, and clears the vector store index.  The underlying SQLite rows
        are **not** physically removed; they remain available for audit.
        """
        self._db.execute(
            "UPDATE memory_index SET status = 'deleted' WHERE layer = ?",
            (self.LAYER_INDEX,),
        )
        self._vector.clear()

    @property
    def size(self) -> int:
        """Number of active L2 episodes in the SQLite store."""
        rows = self._db.query(
            "SELECT COUNT(*) AS cnt FROM memory_index WHERE layer = ? AND status = 'active'",
            (self.LAYER_INDEX,),
        )
        return rows[0]["cnt"] if rows else 0

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _hydrate_from_db(self) -> None:
        """Populate the vector store from pre-existing SQLite episodes.

        Called once at construction time.  When an ``L2EpisodicBuffer`` is
        opened against an existing database the vector store is rebuilt from
        the persisted episodes so that :meth:`retrieve` works immediately
        without re-encoding.
        """
        rows = self._db.query(
            """SELECT mi.id, e.content, e.event_type, mi.importance
               FROM memory_index mi
               JOIN episodes e ON e.memory_id = mi.id
               WHERE mi.layer = ? AND mi.status = 'active'""",
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
