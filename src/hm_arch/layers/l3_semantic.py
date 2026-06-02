"""L3 Semantic Memory — durable semantic triple storage.

L3 stores durable subject–relation–object triples (entity, relation, value)
extracted from episodic memories or inserted directly.

Key behaviours:

* Upsert semantic triples into SQLite + vector index.
* Detect conflicting values for the same (entity, relation) pair.
* Mark older facts as ``superseded`` when a new value is upserted.
* Return only active triples from search; latest value ranks first.

Design notes
------------
* L3 does not inherit from :class:`~hm_arch.layers.base.BaseLayer` because it
  is a persistent layer with a different construction contract (requires a live
  :class:`~hm_arch.storage.sqlite.SQLiteStore`).
* The naming convention ``upsert`` / ``search`` follows the PRD vocabulary for
  L3, analogous to ``encode`` / ``retrieve`` in L2.
* Supersession is conservative: old rows in ``memory_index`` are marked
  ``superseded`` (not deleted) with ``superseded_by`` pointing to the new row.
* The searchable text for a triple is ``"entity relation value"`` so that
  queries like ``"user likes"`` or ``"Python"`` will surface relevant triples.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone

from ..storage.sqlite import SQLiteStore
from ..storage.vector import LocalVectorStore, VectorStoreProtocol


__all__ = [
    "SemanticItem",
    "L3SemanticMemory",
]


# ---------------------------------------------------------------------------
# Return type
# ---------------------------------------------------------------------------


@dataclass
class SemanticItem:
    """A single semantic triple returned by :meth:`L3SemanticMemory.search`.

    Attributes
    ----------
    memory_id:
        Unique identifier shared between ``memory_index`` and ``semantics``.
    layer:
        Always ``3`` for L3 semantic items.
    entity:
        The subject of the triple (e.g. ``"user"``).
    relation:
        The predicate of the triple (e.g. ``"likes"``).
    value:
        The object of the triple (e.g. ``"Python"``).
    confidence:
        Confidence score in ``[0, 1]``.
    version:
        Integer monotonically increasing version for this (entity, relation)
        pair; starts at 1 and increments on each conflict resolution.
    relevance:
        Query-relevance score in ``[0, 1]`` produced by the vector store.
    created_at:
        Timezone-aware UTC datetime of when the triple was persisted.
    metadata:
        Arbitrary caller-supplied key/value pairs stored in ``memory_index``.
    """

    memory_id: str
    layer: int
    entity: str
    relation: str
    value: str
    confidence: float
    version: int
    relevance: float
    created_at: datetime
    metadata: dict = field(default_factory=dict)


# ---------------------------------------------------------------------------
# L3 implementation
# ---------------------------------------------------------------------------


class L3SemanticMemory:
    """Durable semantic triple store (layer 3).

    Persists subject–relation–object triples to SQLite and maintains a vector
    index for similarity search.  Conflicting facts (same entity + relation,
    different value) are handled by marking the older fact as ``superseded``
    and inserting the new value as the canonical active triple.

    Parameters
    ----------
    db:
        An already-connected :class:`~hm_arch.storage.sqlite.SQLiteStore`
        with the schema initialised.  The caller owns the connection lifecycle.
    vector_store:
        Optional vector backend conforming to
        :class:`~hm_arch.storage.vector.VectorStoreProtocol`.  When ``None``
        a fresh :class:`~hm_arch.storage.vector.LocalVectorStore` is created
        and its index is populated from existing SQLite triples.
    default_confidence:
        Confidence score applied when the caller does not supply one.
        Must be in ``[0, 1]``.  Defaults to ``1.0``.
    default_importance:
        Importance score written to ``memory_index`` for new triples.
        Must be in ``[0, 1]``.  Defaults to ``0.5``.

    Examples
    --------
    ::

        from hm_arch.storage.sqlite import SQLiteStore
        from hm_arch.layers.l3_semantic import L3SemanticMemory

        db = SQLiteStore(":memory:").connect()
        db.initialize_schema()
        l3 = L3SemanticMemory(db)

        mid = l3.upsert("user", "likes", "Python")
        results = l3.search("user preference")
        assert results[0].value == "Python"
    """

    LAYER_INDEX: int = 3

    def __init__(
        self,
        db: SQLiteStore,
        vector_store: VectorStoreProtocol | None = None,
        default_confidence: float = 1.0,
        default_importance: float = 0.5,
    ) -> None:
        self._db = db
        self._default_confidence = default_confidence
        self._default_importance = default_importance

        if vector_store is not None:
            self._vector: VectorStoreProtocol = vector_store
        else:
            local = LocalVectorStore()
            self._vector = local
            self._rebuild_vector_index()

    # ------------------------------------------------------------------
    # Primary public interface
    # ------------------------------------------------------------------

    def upsert(
        self,
        entity: str,
        relation: str,
        value: str,
        confidence: float | None = None,
        metadata: dict | None = None,
        source_episodes: list[str] | None = None,
    ) -> str:
        """Persist a semantic triple and return its ``memory_id``.

        If an active triple with the same *entity* and *relation* already
        exists:

        * **Same value** — the call is a no-op (idempotent); the existing
          ``memory_id`` is returned without any writes.
        * **Different value** — the old triple is marked ``superseded`` and
          the new value is inserted as the canonical active fact.

        Parameters
        ----------
        entity:
            Subject of the triple (e.g. ``"user"``).
        relation:
            Predicate / relationship name (e.g. ``"likes"``).
        value:
            Object / fact value (e.g. ``"Python"``).
        confidence:
            Confidence score in ``[0, 1]``.  Defaults to the layer-level
            ``default_confidence``.
        metadata:
            Arbitrary key/value pairs stored in ``memory_index.metadata``.
        source_episodes:
            List of L2 episode ``memory_id`` strings from which this fact
            was extracted.

        Returns
        -------
        str
            The ``memory_id`` of the active triple for this (entity, relation)
            pair after the upsert.
        """
        conf = confidence if confidence is not None else self._default_confidence
        _validate_unit_interval("confidence", conf)
        _validate_unit_interval("importance", self._default_importance)

        existing = self._find_active_triple(entity, relation)

        if existing is not None:
            if existing["value"] == value:
                # Idempotent: same fact already stored.
                return existing["memory_id"]
            # Conflict: insert new triple first, then supersede old one.
            next_version = existing["version"] + 1
            new_mid = self._insert_triple(
                entity=entity,
                relation=relation,
                value=value,
                confidence=conf,
                metadata=metadata,
                source_episodes=source_episodes,
                version=next_version,
            )
            self._supersede(
                old_memory_id=existing["memory_id"],
                new_memory_id=new_mid,
            )
            return new_mid

        # No existing triple: insert as version 1.
        return self._insert_triple(
            entity=entity,
            relation=relation,
            value=value,
            confidence=conf,
            metadata=metadata,
            source_episodes=source_episodes,
            version=1,
        )

    def search(
        self,
        query: str,
        top_k: int = 5,
    ) -> list[SemanticItem]:
        """Return up to *top_k* active triples most relevant to *query*.

        Retrieval is a two-step process:

        1. Query the vector store for candidate ``memory_id`` values ranked by
           token-overlap score.
        2. For each hit, join ``memory_index`` and ``semantics`` in SQLite to
           verify the row is still active and retrieve the full triple data.

        Only ``status = 'active'`` rows are returned.

        Parameters
        ----------
        query:
            Search string.
        top_k:
            Maximum number of results.

        Returns
        -------
        list[SemanticItem]
            Items ordered by relevance descending (highest relevance first).
        """
        vector_hits = self._vector.query(query, top_k=top_k)
        if not vector_hits:
            return []

        items: list[SemanticItem] = []
        for hit in vector_hits:
            row = self._fetch_triple_row(hit.id)
            if row is None:
                continue
            items.append(
                SemanticItem(
                    memory_id=hit.id,
                    layer=self.LAYER_INDEX,
                    entity=row["entity"],
                    relation=row["relation"],
                    value=row["value"],
                    confidence=row["confidence"],
                    version=row["version"],
                    relevance=hit.score,
                    created_at=_parse_iso(row["created_at"]),
                    metadata=json.loads(row["metadata"] or "{}"),
                )
            )
        return items

    def get(self, entity: str, relation: str) -> SemanticItem | None:
        """Return the current active triple for *(entity, relation)*.

        Parameters
        ----------
        entity:
            Subject to look up.
        relation:
            Predicate to look up.

        Returns
        -------
        SemanticItem | None
            The active triple, or ``None`` if no active triple exists for
            this (entity, relation) pair.
        """
        active = self._find_active_triple(entity, relation)
        if active is None:
            return None
        row = self._fetch_triple_row(active["memory_id"])
        if row is None:
            return None
        return SemanticItem(
            memory_id=active["memory_id"],
            layer=self.LAYER_INDEX,
            entity=row["entity"],
            relation=row["relation"],
            value=row["value"],
            confidence=row["confidence"],
            version=row["version"],
            relevance=1.0,
            created_at=_parse_iso(row["created_at"]),
            metadata=json.loads(row["metadata"] or "{}"),
        )

    def count(self) -> int:
        """Return the number of active L3 triples stored in SQLite."""
        rows = self._db.query(
            "SELECT COUNT(*) FROM memory_index WHERE layer = ? AND status = 'active'",
            (self.LAYER_INDEX,),
        )
        return rows[0][0] if rows else 0

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _insert_triple(
        self,
        entity: str,
        relation: str,
        value: str,
        confidence: float,
        metadata: dict | None,
        source_episodes: list[str] | None,
        version: int,
    ) -> str:
        """Write a new triple to memory_index, semantics, and the vector store."""
        mid = uuid.uuid4().hex
        now_str = _iso_now()
        meta_str = json.dumps(dict(metadata) if metadata is not None else {})
        source_str = json.dumps(list(source_episodes) if source_episodes else [])
        searchable_text = f"{entity} {relation} {value}"
        content_hash = hashlib.sha256(searchable_text.encode()).hexdigest()

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
                self._default_importance,
                1.0,
                1.0,
                "active",
                "[]",
                meta_str,
                content_hash,
            ),
        )

        sem_id = uuid.uuid4().hex
        self._db.execute(
            """
            INSERT INTO semantics (
                id, memory_id, entity, relation, value,
                confidence, source_episodes, version
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                sem_id,
                mid,
                entity,
                relation,
                value,
                confidence,
                source_str,
                version,
            ),
        )

        self._vector.upsert(
            mid,
            searchable_text,
            metadata={
                "layer": self.LAYER_INDEX,
                "entity": entity,
                "relation": relation,
            },
        )
        return mid

    def _supersede(self, old_memory_id: str, new_memory_id: str) -> None:
        """Mark *old_memory_id* as superseded and remove it from the vector index."""
        now_str = _iso_now()
        self._db.execute(
            """
            UPDATE memory_index
               SET status        = 'superseded',
                   superseded_by = ?,
                   updated_at    = ?
             WHERE id = ?
            """,
            (new_memory_id, now_str, old_memory_id),
        )
        self._vector.delete(old_memory_id)

    def _find_active_triple(self, entity: str, relation: str) -> dict | None:
        """Return a minimal dict for the active triple for *(entity, relation)*.

        Returns ``None`` when no active triple exists.
        """
        rows = self._db.query(
            """
            SELECT s.memory_id,
                   s.value,
                   s.version
            FROM   semantics    s
            JOIN   memory_index mi ON mi.id = s.memory_id
            WHERE  s.entity   = ?
              AND  s.relation  = ?
              AND  mi.layer    = ?
              AND  mi.status   = 'active'
            """,
            (entity, relation, self.LAYER_INDEX),
        )
        if not rows:
            return None
        r = rows[0]
        return {
            "memory_id": r["memory_id"],
            "value": r["value"],
            "version": r["version"],
        }

    def _fetch_triple_row(self, memory_id: str) -> dict | None:
        """Fetch a joined memory_index + semantics row for *memory_id*.

        Returns a plain dict (column → value) or ``None`` when the row is
        not found or not active.
        """
        rows = self._db.query(
            """
            SELECT mi.id,
                   mi.created_at,
                   mi.metadata,
                   s.entity,
                   s.relation,
                   s.value,
                   s.confidence,
                   s.version
            FROM   memory_index mi
            JOIN   semantics     s ON s.memory_id = mi.id
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
            "metadata": r["metadata"],
            "entity": r["entity"],
            "relation": r["relation"],
            "value": r["value"],
            "confidence": r["confidence"],
            "version": r["version"],
        }

    def _rebuild_vector_index(self) -> None:
        """Populate the in-memory vector store from existing active SQLite triples.

        Called once at construction time when no external vector store is
        supplied.  SQLite is the source of truth; the local vector store is
        derived from it on demand so that restarts do not lose retrieval
        capability.
        """
        rows = self._db.query(
            """
            SELECT mi.id,
                   s.entity,
                   s.relation,
                   s.value
            FROM   memory_index mi
            JOIN   semantics     s ON s.memory_id = mi.id
            WHERE  mi.layer  = ?
              AND  mi.status = 'active'
            """,
            (self.LAYER_INDEX,),
        )
        for row in rows:
            searchable_text = f"{row['entity']} {row['relation']} {row['value']}"
            self._vector.upsert(
                row["id"],
                searchable_text,
                metadata={
                    "layer": self.LAYER_INDEX,
                    "entity": row["entity"],
                    "relation": row["relation"],
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


def _validate_unit_interval(name: str, value: float) -> None:
    """Raise ``ValueError`` when *value* is outside ``[0, 1]``."""
    if not 0.0 <= value <= 1.0:
        raise ValueError(f"{name} must be in [0, 1], got {value!r}")
