"""L3 Semantic Memory — durable subject–relation–object triple store.

L3 stores facts as *semantic triples* ``(entity, relation, value)`` (also
called subject–predicate–object or S–P–O).  Every triple is persisted to two
SQLite tables:

1. ``memory_index`` — one row per memory, holding retention metadata, status,
   and supersession links.
2. ``semantics`` — one row per triple, carrying the entity/relation/value
   content, confidence score, and optional source episode references.

A local in-memory vector index is maintained in parallel so that
:meth:`L3SemanticMemory.search` can find triples by free-text similarity.
Because the canonical data lives in SQLite, the vector index is automatically
rebuilt from the database when the layer is constructed without an external
store — meaning the layer survives process restarts without data loss.

Conflict detection
------------------
When :meth:`upsert` is called with an ``(entity, relation)`` pair that already
has at least one *active* triple with a **different** ``value``, the older
triples are marked ``superseded`` in ``memory_index.status`` and their
``superseded_by`` column is set to the ``memory_id`` of the newly inserted
row.  The new row is always the canonical source of truth for that
``(entity, relation)`` key.

Idempotent re-upsert
--------------------
Calling :meth:`upsert` with an identical ``(entity, relation, value)`` triple
that is already *active* is a no-op at the data level: the existing row is
returned and its version/importance is left unchanged.  Callers can safely
call :meth:`upsert` multiple times without accumulating duplicate rows.

Design notes
------------
* L3 does **not** inherit from :class:`~hm_arch.layers.base.BaseLayer` — it
  has a different construction contract (requires a live
  :class:`~hm_arch.storage.sqlite.SQLiteStore`) and different semantics.
* The vector search text is the concatenation ``"<entity> <relation> <value>"``,
  which lets CJK queries work as long as the underlying
  :class:`~hm_arch.storage.vector.LocalVectorStore` tokenises CJK characters
  individually (it does).
* No LLM is required; all extraction is caller-driven.
* Thread-safety is not guaranteed; callers must synchronise if needed.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone

from ..storage.sqlite import SQLiteStore
from ..storage.vector import (
    LocalVectorStore,
    VectorStoreProtocol,
    _token_overlap_score,
    _tokenize,
)


__all__ = [
    "SemanticFact",
    "L3SemanticMemory",
]

# Layer index constant (L3 = 3).
_LAYER: int = 3


# ---------------------------------------------------------------------------
# Return type
# ---------------------------------------------------------------------------


@dataclass
class SemanticFact:
    """A single semantic triple returned by :meth:`L3SemanticMemory.search`
    or :meth:`L3SemanticMemory.upsert`.

    Attributes
    ----------
    memory_id:
        Unique identifier shared between ``memory_index`` and ``semantics``.
    entity:
        Subject of the triple (e.g. ``"user"``).
    relation:
        Predicate of the triple (e.g. ``"likes"``).
    value:
        Object of the triple (e.g. ``"Python"``).
    confidence:
        Confidence in ``[0, 1]`` that this fact is true.
    version:
        Monotonically increasing version number for this ``(entity, relation)``
        key.  Starts at ``1``; incremented each time a new value supersedes the
        previous one.
    status:
        ``"active"`` for the current canonical fact; ``"superseded"`` for
        older values that have been replaced.
    created_at:
        Timezone-aware UTC datetime of when the fact was first persisted.
    relevance:
        Query-relevance score in ``[0, 1]`` (only meaningful for results
        returned by :meth:`~L3SemanticMemory.search`; ``0.0`` for facts
        returned directly by :meth:`~L3SemanticMemory.upsert`).
    source_episodes:
        List of L2 ``memory_id`` strings that provide evidence for this fact.
    metadata:
        Arbitrary caller-supplied key/value pairs stored in ``memory_index``.
    """

    memory_id: str
    entity: str
    relation: str
    value: str
    confidence: float
    version: int
    status: str
    created_at: datetime
    relevance: float = 0.0
    retention: float = 1.0
    source_episodes: list[str] = field(default_factory=list)
    metadata: dict = field(default_factory=dict)


# ---------------------------------------------------------------------------
# L3 implementation
# ---------------------------------------------------------------------------


class L3SemanticMemory:
    """Durable semantic memory layer (layer 3).

    Stores and retrieves subject–relation–object triples backed by SQLite and a
    local vector index.  Supports idempotent upsert with automatic conflict
    detection and supersession of stale facts.

    Parameters
    ----------
    db:
        An already-connected :class:`~hm_arch.storage.sqlite.SQLiteStore`
        with the schema initialised.  The caller owns the connection lifecycle.
    vector_store:
        Optional vector backend conforming to
        :class:`~hm_arch.storage.vector.VectorStoreProtocol`.  When ``None``
        a fresh :class:`~hm_arch.storage.vector.LocalVectorStore` is created
        and its index is populated from the existing ``semantics`` rows.
    default_confidence:
        Confidence score applied when the caller does not supply one.
        Must be in ``[0, 1]``.  Defaults to ``1.0``.
    default_importance:
        Importance score written to ``memory_index`` at upsert time.
        Must be in ``[0, 1]``.  Defaults to ``0.8`` (semantic facts are
        typically considered more important than raw episodic events).

    Examples
    --------
    ::

        from hm_arch.storage.sqlite import SQLiteStore
        from hm_arch.layers.l3_semantic import L3SemanticMemory

        db = SQLiteStore(":memory:").connect()
        db.initialize_schema()
        l3 = L3SemanticMemory(db)

        mid = l3.upsert("user", "likes", "Python")
        results = l3.search("what does user like", top_k=3)
        assert results[0].entity == "user"
        assert results[0].value == "Python"
    """

    LAYER_INDEX: int = _LAYER

    def __init__(
        self,
        db: SQLiteStore,
        vector_store: VectorStoreProtocol | None = None,
        default_confidence: float = 1.0,
        default_importance: float = 0.8,
        max_memories: int | None = None,
    ) -> None:
        if max_memories is not None and max_memories < 1:
            raise ValueError(f"max_memories must be >= 1, got {max_memories!r}")
        _validate_unit_interval("default_confidence", default_confidence)
        _validate_unit_interval("default_importance", default_importance)
        self._db = db
        self._default_confidence = default_confidence
        self._default_importance = default_importance
        self._max_memories = max_memories

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
        source_episodes: list[str] | None = None,
        metadata: dict | None = None,
        importance: float | None = None,
        similarity_threshold: float | None = None,
    ) -> str:
        """Insert or update a semantic triple ``(entity, relation, value)``.

        Behaviour
        ---------
        1. If an *active* triple with the same ``(entity, relation, value)``
           already exists, return its ``memory_id`` unchanged (idempotent).
        2. If an *active* triple with the same ``(entity, relation)`` but a
           **different** ``value`` exists, mark it (and any others) as
           ``superseded`` and insert the new triple with an incremented
           version number.
        3. If no matching triple exists, insert a fresh one (version 1).

        Parameters
        ----------
        entity:
            Subject of the fact.
        relation:
            Predicate / relationship type.
        value:
            Object / new value for the relation.
        confidence:
            Override for the layer-level default confidence.  Must be in
            ``[0, 1]``.
        source_episodes:
            Optional list of L2 ``memory_id`` strings that justify this fact.
        metadata:
            Arbitrary key/value pairs stored in ``memory_index.metadata``.
        importance:
            Override for the layer-level default importance score.  Must be in
            ``[0, 1]``.
        similarity_threshold:
            When provided, active triples with the same ``(entity, relation)``
            whose ``value`` token similarity meets or exceeds this threshold
            are treated as redundant and merged instead of superseded.

        Returns
        -------
        str
            The ``memory_id`` of the canonical (now-active) triple.
        """
        conf = confidence if confidence is not None else self._default_confidence
        imp = importance if importance is not None else self._default_importance
        _validate_unit_interval("confidence", conf)
        _validate_unit_interval("importance", imp)
        if similarity_threshold is not None:
            _validate_unit_interval("similarity_threshold", similarity_threshold)

        episodes_json = json.dumps(list(source_episodes) if source_episodes else [])
        meta_str = json.dumps(dict(metadata) if metadata is not None else {})

        # --- Step 1: check for exact match (idempotent return) ----------
        existing_id = self._find_active_exact(entity, relation, value)
        if existing_id is not None:
            self._append_source_episodes(existing_id, source_episodes)
            return existing_id

        # --- Step 1b: merge near-duplicate values on the same key -------
        if similarity_threshold is not None:
            similar_id = self._find_active_similar_value(
                entity, relation, value, similarity_threshold
            )
            if similar_id is not None:
                self._append_source_episodes(similar_id, source_episodes)
                return similar_id

        # --- Step 2: find conflicting active triples --------------------
        conflicts = self._find_active_conflicts(entity, relation, value)
        same_key_replacement = bool(conflicts)
        if similarity_threshold is not None:
            conflicts = [
                c
                for c in conflicts
                if _symmetric_text_similarity(value, c["value"]) < similarity_threshold
            ]

        if (
            self._max_memories is not None
            and not same_key_replacement
            and self.count() >= self._max_memories
        ):
            raise ValueError(
                f"max_memories limit ({self._max_memories}) reached; "
                f"cannot upsert ({entity!r}, {relation!r}, {value!r})"
            )

        next_version = 1
        if conflicts:
            # Determine next version from the highest existing version.
            max_version = max(c["version"] for c in conflicts)
            next_version = max_version + 1

        # --- Step 3: insert the new triple (needs memory_id first) -----
        mid = uuid.uuid4().hex
        now_str = _iso_now()

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
                1.0,
                1.0,
                "active",
                "[]",
                meta_str,
                None,
            ),
        )

        self._db.execute(
            """
            INSERT INTO semantics (
                id, memory_id, entity, relation, value,
                confidence, source_episodes, version
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                uuid.uuid4().hex,
                mid,
                entity,
                relation,
                value,
                conf,
                episodes_json,
                next_version,
            ),
        )

        # --- Step 4: supersede conflicting triples ----------------------
        if conflicts:
            for conflict in conflicts:
                self._db.execute(
                    """
                    UPDATE memory_index
                       SET status        = 'superseded',
                           updated_at    = ?,
                           superseded_by = ?
                     WHERE id = ?
                    """,
                    (now_str, mid, conflict["memory_id"]),
                )
                # Remove superseded entry from vector store so it is not
                # returned by future search() calls.
                self._vector.delete(conflict["memory_id"])

        # --- Step 5: upsert into vector store ---------------------------
        triple_text = _triple_text(entity, relation, value)
        self._vector.upsert(
            mid,
            triple_text,
            metadata={
                "layer": self.LAYER_INDEX,
                "entity": entity,
                "relation": relation,
            },
        )

        return mid

    def search(
        self,
        query: str,
        top_k: int = 5,
        entity: str | None = None,
        relation: str | None = None,
    ) -> list[SemanticFact]:
        """Return up to *top_k* active semantic facts most relevant to *query*.

        Retrieval is a two-step process:

        1. Query the vector store for candidate ``memory_id`` values ranked by
           token-overlap relevance.  Any ``entity`` / ``relation`` filters are
           pushed into the vector query as a ``metadata_filter`` so that
           high-scoring unrelated documents cannot displace the filtered match
           from the result window.
        2. For each candidate, join ``memory_index`` and ``semantics`` in
           SQLite to confirm the row is still active and to fetch full content.

        Only rows with ``memory_index.status = 'active'`` are included.

        Parameters
        ----------
        query:
            Free-text search string.  Works with CJK text because the
            underlying :class:`~hm_arch.storage.vector.LocalVectorStore`
            tokenises CJK characters individually.
        top_k:
            Maximum number of results to return.  Returns ``[]`` immediately
            when ``top_k <= 0``.
        entity:
            When provided, only triples with this exact entity are returned.
            Passed as a ``metadata_filter`` to the vector store so that
            unrelated documents cannot crowd out the match.
        relation:
            When provided, only triples with this exact relation are returned.
            Passed as a ``metadata_filter`` to the vector store so that
            unrelated documents cannot crowd out the match.

        Returns
        -------
        list[SemanticFact]
            Facts ordered by relevance descending.  The highest-relevance
            (latest-value) fact for any ``(entity, relation)`` key appears
            first because superseded triples are excluded.
        """
        if top_k <= 0:
            return []

        # Push entity/relation filters into the vector query so that
        # many high-scoring unrelated facts cannot displace the target from
        # the top-k window.  With filter pushdown, top_k candidates are
        # sufficient (no need for the previous 4× over-fetch heuristic).
        metadata_filter: dict | None = None
        _filter: dict = {}
        if entity is not None:
            _filter["entity"] = entity
        if relation is not None:
            _filter["relation"] = relation
        if _filter:
            metadata_filter = _filter

        vector_hits = self._vector.query(query, top_k=top_k, metadata_filter=metadata_filter)
        if not vector_hits:
            return []

        results: list[SemanticFact] = []
        seen: set[str] = set()
        for hit in vector_hits:
            if hit.id in seen:
                continue
            row = self._fetch_semantic_row(hit.id)
            if row is None:
                continue
            seen.add(hit.id)
            results.append(
                SemanticFact(
                    memory_id=hit.id,
                    entity=row["entity"],
                    relation=row["relation"],
                    value=row["value"],
                    confidence=row["confidence"],
                    version=row["version"],
                    status=row["status"],
                    created_at=_parse_iso(row["created_at"]),
                    relevance=hit.score,
                    retention=row["current_retention"],
                    source_episodes=json.loads(row["source_episodes"] or "[]"),
                    metadata=json.loads(row["metadata"] or "{}"),
                )
            )
            if len(results) >= top_k:
                break

        return results

    def get_by_entity_relation(
        self,
        entity: str,
        relation: str,
    ) -> SemanticFact | None:
        """Return the single active fact for ``(entity, relation)``, or ``None``.

        This is a direct SQLite lookup, not a vector search.  Useful for
        deterministic point-lookups (e.g. ``"what does user like?"``).
        """
        rows = self._db.query(
            """
            SELECT mi.id,
                   mi.created_at,
                   mi.importance,
                   mi.current_retention,
                   mi.status,
                   mi.metadata,
                   s.entity,
                   s.relation,
                   s.value,
                   s.confidence,
                   s.source_episodes,
                   s.version
            FROM   memory_index mi
            JOIN   semantics    s ON s.memory_id = mi.id
            WHERE  s.entity   = ?
              AND  s.relation = ?
              AND  mi.layer   = ?
              AND  mi.status  = 'active'
            ORDER  BY s.version DESC
            LIMIT  1
            """,
            (entity, relation, self.LAYER_INDEX),
        )
        if not rows:
            return None
        r = rows[0]
        return SemanticFact(
            memory_id=r["id"],
            entity=r["entity"],
            relation=r["relation"],
            value=r["value"],
            confidence=r["confidence"],
            version=r["version"],
            status=r["status"],
            created_at=_parse_iso(r["created_at"]),
            relevance=0.0,
            retention=r["current_retention"],
            source_episodes=json.loads(r["source_episodes"] or "[]"),
            metadata=json.loads(r["metadata"] or "{}"),
        )

    def merge_redundant_active_pairs(self, threshold: float) -> int:
        """Merge active facts that share ``(entity, relation)`` and similar values.

        Only pairs with the same entity and relation are considered.  Values
        must meet or exceed *threshold* token similarity; dissimilar values
        on the same key remain separate (conflicts are handled by
        :meth:`upsert`).  Facts with different entities or relations are never
        merged, even when their combined triple text overlaps.

        Pairs are evaluated in deterministic ``memory_id`` order.  The
        canonical fact is the one with higher ``importance``; ties break on
        ascending ``memory_id``.

        Returns the number of facts merged away (superseded).
        """
        _validate_unit_interval("threshold", threshold)
        facts = self._list_active_facts()
        removed: set[str] = set()
        merged = 0

        for i, fact_a in enumerate(facts):
            if fact_a["memory_id"] in removed:
                continue
            for fact_b in facts[i + 1 :]:
                if fact_b["memory_id"] in removed:
                    continue
                if (
                    fact_a["entity"] != fact_b["entity"]
                    or fact_a["relation"] != fact_b["relation"]
                ):
                    continue

                if (
                    _symmetric_text_similarity(fact_a["value"], fact_b["value"])
                    < threshold
                ):
                    continue

                canonical, duplicate = self._pick_canonical_pair(fact_a, fact_b)
                self._merge_into(canonical["memory_id"], duplicate["memory_id"])
                removed.add(duplicate["memory_id"])
                merged += 1

        return merged

    def remove_from_vector_index(self, memory_id: str) -> bool:
        """Remove *memory_id* from the vector index without deleting SQLite rows."""
        return self._vector.delete(memory_id)

    def count(self, status: str = "active") -> int:
        """Return the number of L3 triples with the given *status* in SQLite.

        Parameters
        ----------
        status:
            One of ``"active"`` or ``"superseded"`` (or any custom value).
            Defaults to ``"active"``.
        """
        rows = self._db.query(
            "SELECT COUNT(*) FROM memory_index WHERE layer = ? AND status = ?",
            (self.LAYER_INDEX, status),
        )
        return rows[0][0] if rows else 0

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _find_active_exact(self, entity: str, relation: str, value: str) -> str | None:
        """Return the ``memory_id`` of an existing active exact-match triple.

        Returns ``None`` when no such triple exists.
        """
        rows = self._db.query(
            """
            SELECT mi.id
            FROM   memory_index mi
            JOIN   semantics    s ON s.memory_id = mi.id
            WHERE  s.entity   = ?
              AND  s.relation = ?
              AND  s.value    = ?
              AND  mi.layer   = ?
              AND  mi.status  = 'active'
            LIMIT  1
            """,
            (entity, relation, value, self.LAYER_INDEX),
        )
        return rows[0]["id"] if rows else None

    def _list_active_facts(self) -> list[dict]:
        """Return active semantic rows ordered by ``memory_id``."""
        rows = self._db.query(
            """
            SELECT mi.id AS memory_id,
                   mi.importance,
                   s.entity,
                   s.relation,
                   s.value,
                   s.source_episodes
            FROM   memory_index mi
            JOIN   semantics    s ON s.memory_id = mi.id
            WHERE  mi.layer  = ?
              AND  mi.status = 'active'
            ORDER  BY mi.id
            """,
            (self.LAYER_INDEX,),
        )
        return [
            {
                "memory_id": row["memory_id"],
                "importance": row["importance"],
                "entity": row["entity"],
                "relation": row["relation"],
                "value": row["value"],
                "source_episodes": json.loads(row["source_episodes"] or "[]"),
            }
            for row in rows
        ]

    def _find_active_similar_value(
        self,
        entity: str,
        relation: str,
        value: str,
        threshold: float,
    ) -> str | None:
        """Return the ``memory_id`` of an active near-duplicate value, if any."""
        rows = self._db.query(
            """
            SELECT mi.id AS memory_id,
                   s.value
            FROM   memory_index mi
            JOIN   semantics    s ON s.memory_id = mi.id
            WHERE  s.entity   = ?
              AND  s.relation = ?
              AND  s.value   != ?
              AND  mi.layer   = ?
              AND  mi.status  = 'active'
            ORDER  BY mi.id
            """,
            (entity, relation, value, self.LAYER_INDEX),
        )
        for row in rows:
            if _symmetric_text_similarity(value, row["value"]) >= threshold:
                return row["memory_id"]
        return None

    def _append_source_episodes(
        self,
        memory_id: str,
        source_episodes: list[str] | None,
    ) -> None:
        """Union new episode ids into an active semantic fact."""
        if not source_episodes:
            return

        rows = self._db.query(
            "SELECT source_episodes FROM semantics WHERE memory_id = ?",
            (memory_id,),
        )
        if not rows:
            return

        existing = json.loads(rows[0]["source_episodes"] or "[]")
        merged = list(dict.fromkeys([*existing, *source_episodes]))
        if merged == existing:
            return

        self._db.execute(
            """
            UPDATE semantics
               SET source_episodes = ?
             WHERE memory_id = ?
            """,
            (json.dumps(merged), memory_id),
        )

    def _pick_canonical_pair(self, left: dict, right: dict) -> tuple[dict, dict]:
        """Choose canonical/duplicate facts deterministically."""
        if left["importance"] > right["importance"]:
            return left, right
        if right["importance"] > left["importance"]:
            return right, left
        if left["memory_id"] <= right["memory_id"]:
            return left, right
        return right, left

    def _merge_into(self, canonical_id: str, duplicate_id: str) -> None:
        """Merge *duplicate_id* into *canonical_id* and supersede the duplicate."""
        if canonical_id == duplicate_id:
            return

        dup_rows = self._db.query(
            "SELECT source_episodes FROM semantics WHERE memory_id = ?",
            (duplicate_id,),
        )
        if dup_rows:
            dup_episodes = json.loads(dup_rows[0]["source_episodes"] or "[]")
            self._append_source_episodes(canonical_id, dup_episodes)

        now_str = _iso_now()
        self._db.execute(
            """
            UPDATE memory_index
               SET status        = 'superseded',
                   updated_at    = ?,
                   superseded_by = ?
             WHERE id = ?
            """,
            (now_str, canonical_id, duplicate_id),
        )
        self._vector.delete(duplicate_id)

    def _find_active_conflicts(
        self, entity: str, relation: str, value: str
    ) -> list[dict]:
        """Return rows for active triples with same (entity, relation) but different value.

        Each returned dict has ``memory_id`` and ``version`` keys.
        """
        rows = self._db.query(
            """
            SELECT mi.id AS memory_id,
                   s.version,
                   s.value
            FROM   memory_index mi
            JOIN   semantics    s ON s.memory_id = mi.id
            WHERE  s.entity   = ?
              AND  s.relation = ?
              AND  s.value   != ?
              AND  mi.layer   = ?
              AND  mi.status  = 'active'
            """,
            (entity, relation, value, self.LAYER_INDEX),
        )
        return [
            {
                "memory_id": r["memory_id"],
                "version": r["version"],
                "value": r["value"],
            }
            for r in rows
        ]

    def _fetch_semantic_row(self, memory_id: str) -> dict | None:
        """Fetch a joined memory_index + semantics row for *memory_id*.

        Returns ``None`` when not found or when the row is not active.
        """
        rows = self._db.query(
            """
            SELECT mi.id,
                   mi.created_at,
                   mi.importance,
                   mi.current_retention,
                   mi.status,
                   mi.metadata,
                   s.entity,
                   s.relation,
                   s.value,
                   s.confidence,
                   s.source_episodes,
                   s.version
            FROM   memory_index mi
            JOIN   semantics    s ON s.memory_id = mi.id
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
            "status": r["status"],
            "metadata": r["metadata"],
            "entity": r["entity"],
            "relation": r["relation"],
            "value": r["value"],
            "confidence": r["confidence"],
            "source_episodes": r["source_episodes"],
            "version": r["version"],
        }

    def _rebuild_vector_index(self) -> None:
        """Populate the in-memory vector store from existing active SQLite rows.

        Called once at construction (when no external vector store is supplied)
        so that restarts do not lose retrieval capability.  SQLite is the
        source of truth; the local vector store is a derived index.
        """
        rows = self._db.query(
            """
            SELECT mi.id,
                   s.entity,
                   s.relation,
                   s.value
            FROM   memory_index mi
            JOIN   semantics    s ON s.memory_id = mi.id
            WHERE  mi.layer  = ?
              AND  mi.status = 'active'
            """,
            (self.LAYER_INDEX,),
        )
        for row in rows:
            self._vector.upsert(
                row["id"],
                _triple_text(row["entity"], row["relation"], row["value"]),
                metadata={
                    "layer": self.LAYER_INDEX,
                    "entity": row["entity"],
                    "relation": row["relation"],
                },
            )


# ---------------------------------------------------------------------------
# Private utilities
# ---------------------------------------------------------------------------


def _triple_text(entity: str, relation: str, value: str) -> str:
    """Produce the canonical vector-store text for a triple."""
    return f"{entity} {relation} {value}"


def _symmetric_text_similarity(left: str, right: str) -> float:
    """Deterministic token-overlap similarity in ``[0, 1]``."""
    left_tokens = _tokenize(left)
    right_tokens = _tokenize(right)
    if not left_tokens or not right_tokens:
        return 0.0
    return max(
        _token_overlap_score(left_tokens, right_tokens),
        _token_overlap_score(right_tokens, left_tokens),
    )


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
