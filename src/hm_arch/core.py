"""HMArch — public facade for the HM-Arch memory SDK.

Wires together L1 (working memory), L2 (episodic buffer), and L3 (semantic
memory) into a single ergonomic interface.  All persistence uses SQLite with
a local deterministic vector fallback so the facade works fully offline
without any external API keys.

Scoring formula::

    score = retention × relevance × layer_priority

where *layer_priority* comes from :attr:`MemoryConfig.layer_priorities`.

Usage example::

    from hm_arch import HMArch, EventType

    memory = HMArch(db_path=":memory:")
    memory.add("用户偏好 Python", event_type=EventType.CONVERSATION)
    results = memory.search("用户喜欢什么语言", top_k=5)
    for item in results.results:
        print(item.layer, item.score, item.content)
"""

from __future__ import annotations

import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator, Optional

from .config import MemoryConfig
from .consolidation import ConsolidationEngine
from .forgetting.decay import predict_retention_curve
from .layers.l1_working import L1WorkingMemory
from .layers.l2_episodic import L2EpisodicBuffer
from .layers.l3_semantic import L3SemanticMemory
from .storage.sqlite import SQLiteStore
from .storage.vector import _token_overlap_score, _tokenize
from .types import (
    ConsolidationReport,
    EventType,
    MemoryItem,
    MemoryReceipt,
    MemoryStats,
    RetentionCurve,
    SearchResult,
)

__all__ = ["HMArch"]


def _relevance(query: str, text: str) -> float:
    """Token-overlap relevance score between *query* and *text* in ``[0, 1]``."""
    return _token_overlap_score(_tokenize(query), _tokenize(text))


_RETENTION_BUCKETS: tuple[tuple[str, float, float], ...] = (
    ("0-0.25", 0.0, 0.25),
    ("0.25-0.5", 0.25, 0.5),
    ("0.5-0.75", 0.5, 0.75),
    ("0.75-1.0", 0.75, 1.0000001),
)


def _retention_histogram(db: SQLiteStore) -> dict[str, int]:
    """Bucket active ``memory_index`` rows by ``current_retention``."""
    counts = {label: 0 for label, _, _ in _RETENTION_BUCKETS}
    rows = db.query(
        "SELECT current_retention FROM memory_index WHERE status = 'active'"
    )
    for row in rows:
        r = float(row["current_retention"])
        for label, low, high in _RETENTION_BUCKETS:
            if low <= r < high:
                counts[label] += 1
                break
    return counts


def _review_queue_length(db: SQLiteStore) -> int:
    rows = db.query("SELECT COUNT(*) AS n FROM review_queue")
    return int(rows[0]["n"]) if rows else 0


def _last_consolidation_at(db: SQLiteStore) -> datetime | None:
    rows = db.query(
        """
        SELECT completed_at
        FROM   consolidation_log
        ORDER  BY completed_at DESC
        LIMIT  1
        """
    )
    if not rows:
        return None
    return _parse_iso_timestamp(rows[0]["completed_at"])


def _parse_iso_timestamp(iso_str: str) -> datetime:
    dt = datetime.fromisoformat(iso_str)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _database_size_mb(db: SQLiteStore) -> float:
    """Approximate on-disk database size in megabytes."""
    path = db.path
    if path != ":memory:":
        p = Path(path)
        if p.is_file():
            return p.stat().st_size / (1024 * 1024)

    page_rows = db.query("PRAGMA page_count")
    size_rows = db.query("PRAGMA page_size")
    if not page_rows or not size_rows:
        return 0.0
    pages = int(page_rows[0][0])
    page_size = int(size_rows[0][0])
    return (pages * page_size) / (1024 * 1024)


class HMArch:
    """Public facade for the HM-Arch memory SDK.

    Creates and owns the underlying storage and layer objects.  The SQLite
    connection is opened at construction and closed when :meth:`close` is
    called (or when used as a context manager).

    Parameters
    ----------
    db_path:
        Filesystem path (or ``":memory:"`` for in-process tests) to the
        SQLite database.  Ignored when *config* is supplied.
    config:
        Optional :class:`MemoryConfig` override.  When provided the
        ``db_path`` parameter is ignored in favour of ``config.db_path``.

    Examples
    --------
    ::

        memory = HMArch(db_path=":memory:")
        memory.add("用户偏好 Python", event_type=EventType.CONVERSATION)
        results = memory.search("用户喜欢什么语言", top_k=5)
        assert results.results[0].score > 0
        memory.close()

    Context-manager form (preferred)::

        with HMArch(db_path=":memory:") as memory:
            memory.add("Python is great")
            results = memory.search("Python")
    """

    def __init__(
        self,
        db_path: str = "./.agent_memory.db",
        config: Optional[MemoryConfig] = None,
    ) -> None:
        if config is None:
            config = MemoryConfig(db_path=db_path)
        self._config = config

        self._db = SQLiteStore(self._config.db_path)
        self._db.connect()
        self._db.initialize_schema()

        self._l1 = L1WorkingMemory()
        self._l2 = L2EpisodicBuffer(self._db)
        self._l3 = L3SemanticMemory(self._db)

    # ------------------------------------------------------------------
    # Primary public interface
    # ------------------------------------------------------------------

    def add(
        self,
        content: str,
        event_type: EventType = EventType.OBSERVATION,
        metadata: Optional[dict] = None,
        importance: Optional[float] = None,
    ) -> MemoryReceipt:
        """Store *content* in working memory (L1) and the episodic buffer (L2).

        ``add()`` always succeeds without an external LLM key.  L3 semantic
        extraction is **not** triggered here; call :meth:`consolidate` to
        replay episodic memories and upsert semantic triples.

        Parameters
        ----------
        content:
            Text to remember.
        event_type:
            Classification for the event; defaults to
            :attr:`~hm_arch.types.EventType.OBSERVATION`.
        metadata:
            Optional key/value pairs attached to the memory record.
        importance:
            Importance score in ``[0, 1]``.  When omitted the L2 layer
            default (``0.5``) is applied.

        Returns
        -------
        MemoryReceipt
            Confirmation including the ``memory_id`` assigned by L2, which
            is the durable database-backed identifier for the event.
        """
        # L1 in-memory working memory — fast access within the current session
        self._l1.add(content, metadata=metadata)

        # L2 episodic buffer — persisted to SQLite, survives restarts
        l2_mid = self._l2.encode(
            content,
            event_type=event_type,
            metadata=metadata,
            importance=importance,
        )

        imp = importance if importance is not None else 0.5
        return MemoryReceipt(
            memory_id=l2_mid,
            layer=2,
            importance=imp,
            initial_strength=1.0,
            decay_estimate={"1d": 0.92, "7d": 0.65, "30d": 0.26},
            consolidation_scheduled=datetime.now(tz=timezone.utc),
        )

    def search(
        self,
        query: str,
        top_k: int = 5,
    ) -> SearchResult:
        """Return the top-*k* memories most relevant to *query*.

        Queries L1 working memory, L2 episodic buffer, and L3 semantic
        memory.  Candidates from all three layers are merged, deduplicated by
        ``memory_id``, scored as::

            score = retention × relevance × layer_priority

        and sorted descending so the highest-scoring result is first.

        CJK text is tokenised character-by-character so queries like
        ``"用户喜欢什么语言"`` match content like ``"用户偏好 Python"`` via
        shared character tokens.

        Parameters
        ----------
        query:
            Free-text search string.
        top_k:
            Maximum number of :class:`~hm_arch.types.MemoryItem` results to
            return.  Defaults to ``5``.

        Returns
        -------
        SearchResult
            Container with ranked :class:`~hm_arch.types.MemoryItem` hits
            plus diagnostic metadata (total candidates scanned, timing,
            per-layer breakdown).
        """
        t0 = time.monotonic()
        priorities = self._config.layer_priorities

        candidates: list[MemoryItem] = []
        seen_ids: set[str] = set()
        source_breakdown: dict[int, int] = {1: 0, 2: 0, 3: 0}

        # ---- L1: in-memory working memory --------------------------------
        # Pull up to top_k candidates from each layer; the merged pool is
        # then re-ranked by the combined score formula.
        l1_hits = self._l1.retrieve(query, top_k=top_k)
        source_breakdown[1] = len(l1_hits)
        l1_priority = priorities.get("L1", 0.9)
        for item in l1_hits:
            if item.memory_id in seen_ids:
                continue
            seen_ids.add(item.memory_id)
            rel = _relevance(query, item.content)
            # In-session items have no decay yet; retention = 1.0
            score = 1.0 * rel * l1_priority
            candidates.append(
                MemoryItem(
                    memory_id=item.memory_id,
                    layer=1,
                    content=item.content,
                    retention=1.0,
                    relevance=rel,
                    score=score,
                    metadata=item.metadata,
                )
            )

        # ---- L2: episodic buffer -----------------------------------------
        l2_hits = self._l2.retrieve(query, top_k=top_k)
        source_breakdown[2] = len(l2_hits)
        l2_priority = priorities.get("L2", 0.7)
        for item in l2_hits:
            if item.memory_id in seen_ids:
                continue
            seen_ids.add(item.memory_id)
            score = item.retention * item.relevance * l2_priority
            candidates.append(
                MemoryItem(
                    memory_id=item.memory_id,
                    layer=2,
                    content=item.content,
                    retention=item.retention,
                    relevance=item.relevance,
                    score=score,
                    metadata=item.metadata,
                )
            )

        # ---- L3: semantic memory -----------------------------------------
        l3_hits = self._l3.search(query, top_k=top_k)
        source_breakdown[3] = len(l3_hits)
        l3_priority = priorities.get("L3", 0.8)
        for item in l3_hits:
            if item.memory_id in seen_ids:
                continue
            seen_ids.add(item.memory_id)
            content = f"{item.entity} {item.relation} {item.value}"
            score = item.retention * item.relevance * l3_priority
            candidates.append(
                MemoryItem(
                    memory_id=item.memory_id,
                    layer=3,
                    content=content,
                    retention=item.retention,
                    relevance=item.relevance,
                    score=score,
                    metadata=item.metadata,
                )
            )

        # Sort descending by score; stable sort preserves layer order as tiebreak
        candidates.sort(key=lambda x: -x.score)

        elapsed_ms = (time.monotonic() - t0) * 1000
        total_scanned = sum(source_breakdown.values())

        return SearchResult(
            results=candidates[:top_k],
            total_scanned=total_scanned,
            timing_ms=elapsed_ms,
            source_breakdown=source_breakdown,
        )

    def consolidate(self) -> ConsolidationReport:
        """Run a consolidation cycle over persisted memories.

        Applies layer-specific decay, replays a sample of L2 episodes,
        extracts semantic triples into L3 (offline pattern-based fallback),
        schedules reviews for important low-retention items, and writes an
        audit row to ``consolidation_log``.

        Returns
        -------
        ConsolidationReport
            Counts of extracted semantics, scheduled reviews, and related
            maintenance actions.
        """
        engine = ConsolidationEngine(
            self._db,
            self._l2,
            self._l3,
            config=self._config,
        )
        return engine.run_consolidation_cycle()

    def get_retention_curve(
        self,
        layer: int,
        days: Optional[list[int]] = None,
    ) -> RetentionCurve:
        """Return predicted retention samples for L2 or L3.

        Parameters
        ----------
        layer:
            Memory layer index: ``2`` for episodic (biexponential decay) or
            ``3`` for semantic (power-law decay).
        days:
            Optional sorted day offsets at which to sample retention.
            Defaults to ``[1, 3, 7, 14, 30, 60, 90]``.

        Returns
        -------
        RetentionCurve
            Sampled retention values plus suggested review and archive days.
        """
        return predict_retention_curve(
            layer=layer,
            config=self._config,
            days=days,
        )

    def get_stats(self) -> MemoryStats:
        """Return aggregated statistics about the memory store.

        Counts include in-session L1 items plus persisted L2/L3 rows with
        ``status = 'active'``.  Retention histogram buckets are computed from
        ``memory_index.current_retention`` for all active persisted memories.
        """
        by_layer = {
            0: 0,
            1: self._l1.size,
            2: self._l2.count(),
            3: self._l3.count(status="active"),
        }
        total_memories = sum(by_layer.values())

        retention_distribution = _retention_histogram(self._db)
        review_queue_length = _review_queue_length(self._db)
        last_consolidation_at = _last_consolidation_at(self._db)
        storage_size_mb = _database_size_mb(self._db)

        return MemoryStats(
            total_memories=total_memories,
            by_layer=by_layer,
            storage_size_mb=storage_size_mb,
            retention_distribution=retention_distribution,
            review_queue_length=review_queue_length,
            last_consolidation_at=last_consolidation_at,
        )

    @contextmanager
    def context(self) -> Iterator["HMArch"]:
        """Save and restore L1 working-memory session state.

        On entry, a snapshot of the current L1 store is taken.  On exit (even
        when an exception is raised), L1 is restored to that snapshot so
        ephemeral session additions inside the block do not leak into the
        outer agent turn.  L2/L3 persisted data is unaffected.

        Examples
        --------
        ::

            memory.add("baseline context")
            with memory.context():
                memory.add("temporary task note")
            # L1 is back to the pre-block snapshot; L2 still has both adds.
        """
        saved_l1 = self._l1.snapshot()
        try:
            yield self
        finally:
            self._l1.load_snapshot(saved_l1)

    # ------------------------------------------------------------------
    # Connection lifecycle
    # ------------------------------------------------------------------

    def close(self) -> None:
        """Commit and close the underlying SQLite connection."""
        self._db.close()

    def __enter__(self) -> "HMArch":
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.close()
