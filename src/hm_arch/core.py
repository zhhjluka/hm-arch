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

import copy
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Generator, Optional

from .config import MemoryConfig
from .layers.base import LayerItem
from .layers.l1_working import L1WorkingMemory
from .layers.l2_episodic import L2EpisodicBuffer
from .layers.l3_semantic import L3SemanticMemory
from .storage.sqlite import SQLiteStore
from .storage.vector import _token_overlap_score, _tokenize
from .types import EventType, MemoryItem, MemoryReceipt, MemoryStats, SearchResult

__all__ = ["HMArch"]


def _relevance(query: str, text: str) -> float:
    """Token-overlap relevance score between *query* and *text* in ``[0, 1]``."""
    return _token_overlap_score(_tokenize(query), _tokenize(text))


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
        extraction is **not** triggered here; it happens during
        ``consolidate()`` (a later milestone).

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

    def get_stats(self) -> MemoryStats:
        """Return aggregated memory statistics for inspection and monitoring.

        Counts active memories per layer (L1 in-memory, L2/L3 from SQLite),
        reports on-disk storage size, summarises retention values, and
        surfaces consolidation metadata from the database.
        """
        by_layer = {
            0: 0,
            1: self._l1.size,
            2: self._l2.count(),
            3: self._l3.count(),
        }
        total_memories = sum(by_layer.values())

        retention_distribution = self._retention_distribution()
        review_queue_length = self._review_queue_length()
        last_consolidation_at = self._last_consolidation_at()

        return MemoryStats(
            total_memories=total_memories,
            by_layer=by_layer,
            storage_size_mb=self._storage_size_mb(),
            retention_distribution=retention_distribution,
            review_queue_length=review_queue_length,
            last_consolidation_at=last_consolidation_at,
        )

    @contextmanager
    def context(self) -> Generator[None, None, None]:
        """Save and restore L1 working-memory session state.

        Use this when an agent sub-task should temporarily add working-memory
        items without polluting the parent session.  L2/L3 persisted memories
        are unaffected; only the in-memory L1 snapshot is saved on entry and
        restored on exit.

        Examples
        --------
        ::

            memory.add("parent context")
            with memory.context():
                memory.add("temporary sub-task note")
            # L1 again contains only "parent context"
        """
        saved: list[LayerItem] = copy.deepcopy(self._l1.snapshot())
        try:
            yield
        finally:
            self._l1.restore_snapshot(saved)

    # ------------------------------------------------------------------
    # Stats helpers
    # ------------------------------------------------------------------

    _RETENTION_BUCKETS: tuple[tuple[str, float, float], ...] = (
        ("0-0.25", 0.0, 0.25),
        ("0.25-0.5", 0.25, 0.5),
        ("0.5-0.75", 0.5, 0.75),
        ("0.75-1.0", 0.75, 1.000001),
    )

    def _retention_distribution(self) -> dict[str, int]:
        """Histogram of ``current_retention`` for active indexed memories."""
        buckets = {label: 0 for label, _, _ in self._RETENTION_BUCKETS}
        rows = self._db.query(
            "SELECT current_retention FROM memory_index WHERE status = 'active'"
        )
        for row in rows:
            value = float(row["current_retention"])
            for label, low, high in self._RETENTION_BUCKETS:
                if low <= value < high:
                    buckets[label] += 1
                    break
        return buckets

    def _review_queue_length(self) -> int:
        rows = self._db.query("SELECT COUNT(*) AS n FROM review_queue")
        return int(rows[0]["n"]) if rows else 0

    def _last_consolidation_at(self) -> datetime | None:
        rows = self._db.query(
            """
            SELECT completed_at
            FROM   consolidation_log
            ORDER  BY completed_at DESC
            LIMIT  1
            """
        )
        if not rows:
            return None
        dt = datetime.fromisoformat(rows[0]["completed_at"])
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt

    def _storage_size_mb(self) -> float:
        """Approximate database size in megabytes."""
        db_path = self._db.path
        if db_path != ":memory:":
            path = Path(db_path)
            if path.exists():
                return path.stat().st_size / (1024 * 1024)
            return 0.0

        page_count_rows = self._db.query("PRAGMA page_count")
        page_size_rows = self._db.query("PRAGMA page_size")
        page_count = int(page_count_rows[0][0]) if page_count_rows else 0
        page_size = int(page_size_rows[0][0]) if page_size_rows else 0
        return (page_count * page_size) / (1024 * 1024)

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
