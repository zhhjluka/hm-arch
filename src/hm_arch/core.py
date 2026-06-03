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
    report = memory.consolidate()
    curve = memory.get_retention_curve(layer=2)
"""

from __future__ import annotations

import json
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator, Optional

from .config import MemoryConfig
from .consolidation.replay import ConsolidationEngine
from .context import AgentContext
from .forgetting.decay import predict_memory_retention_curve, predict_retention_curve
from .layers.l1_working import L1WorkingMemory
from .layers.l2_episodic import L2EpisodicBuffer
from .layers.l3_semantic import L3SemanticMemory
from .layers.l4_ltm import L4EpisodicLTM
from .layers.l6_meta import L6MetaMemory
from .storage.sqlite import SQLiteStore
from .storage.vector import _token_overlap_score, _tokenize
from .types import (
    ConsolidationReport,
    EventType,
    ForgetResult,
    MemoryItem,
    MemoryReceipt,
    MemoryStats,
    RetentionCurve,
    SearchResult,
)

__all__ = ["HMArch", "AgentContext"]

_DEFAULT_SEARCH_LAYERS: tuple[int, ...] = (1, 2, 3, 4)


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


def _resolve_archive_root(config: MemoryConfig) -> Path:
    """Return the filesystem root for L4 gzip archives."""
    if config.archive_root is not None:
        return Path(config.archive_root)
    if config.db_path == ":memory:":
        return Path("./.agent_memory_data")
    return Path(config.db_path).parent / "agent_data"


def _delete_threshold_for_layer(layer: int, config: MemoryConfig) -> float:
    if layer == 2:
        return config.l2_delete_threshold
    if layer == 3:
        return config.l3_delete_threshold
    return 0.0


def _archive_threshold_for_layer(layer: int, config: MemoryConfig) -> float:
    if layer == 2:
        return config.l2_archive_threshold
    if layer == 3:
        return config.l3_archive_threshold
    return 0.0


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
        self._l4 = L4EpisodicLTM(_resolve_archive_root(self._config))
        self._l6 = L6MetaMemory(self._db)

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
        *,
        min_retention: float = 0.0,
        layer_filter: list[int] | None = None,
    ) -> SearchResult:
        """Return the top-*k* memories most relevant to *query*.

        Queries L1 working memory, L2 episodic buffer, L3 semantic memory, and
        L4 archived episodic memories.  Candidates from all layers are merged,
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
        min_retention:
            Exclude hits whose retention is strictly below this value.
            Defaults to ``0.0`` for backward compatibility.
        layer_filter:
            When provided, only search these layer indices (e.g. ``[1, 2, 3]``).
            When ``None``, all supported layers ``(1, 2, 3, 4)`` are queried.

        Returns
        -------
        SearchResult
            Container with ranked :class:`~hm_arch.types.MemoryItem` hits
            plus diagnostic metadata (total candidates scanned, timing,
            per-layer breakdown).
        """
        if not 0.0 <= min_retention <= 1.0:
            raise ValueError(
                f"min_retention must be in [0, 1], got {min_retention!r}"
            )

        allowed_layers = (
            set(layer_filter) if layer_filter is not None else set(_DEFAULT_SEARCH_LAYERS)
        )

        t0 = time.monotonic()
        priorities = self._config.layer_priorities

        candidates: list[MemoryItem] = []
        seen_ids: set[str] = set()
        source_breakdown: dict[int, int] = {1: 0, 2: 0, 3: 0, 4: 0}

        # ---- L1: in-memory working memory --------------------------------
        # Pull up to top_k candidates from each layer; the merged pool is
        # then re-ranked by the combined score formula.
        l1_hits = (
            self._l1.retrieve(query, top_k=top_k) if 1 in allowed_layers else []
        )
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
        l2_hits = (
            self._l2.retrieve(query, top_k=top_k) if 2 in allowed_layers else []
        )
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
        l3_hits = (
            self._l3.search(query, top_k=top_k) if 3 in allowed_layers else []
        )
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

        # ---- L4: archived episodic long-term memory ----------------------
        l4_hits = (
            self._l4.search(query, top_k=top_k) if 4 in allowed_layers else []
        )
        source_breakdown[4] = len(l4_hits)
        l4_priority = priorities.get("L4", 0.5)
        for hit in l4_hits:
            record = hit.record
            if record.memory_id in seen_ids:
                continue
            archived_rows = self._db.query(
                """
                SELECT id FROM memory_index
                WHERE id = ? AND status = 'archived' AND layer = 4
                """,
                (record.memory_id,),
            )
            if not archived_rows:
                continue
            seen_ids.add(record.memory_id)
            rel = hit.relevance
            score = record.retention * rel * l4_priority
            metadata = dict(record.metadata)
            metadata.setdefault("source_l2_memory_id", record.memory_id)
            candidates.append(
                MemoryItem(
                    memory_id=record.memory_id,
                    layer=4,
                    content=record.content,
                    retention=record.retention,
                    relevance=rel,
                    score=score,
                    metadata=metadata,
                )
            )

        # Sort descending by score; stable sort preserves layer order as tiebreak
        candidates.sort(key=lambda x: -x.score)

        filtered = [
            item
            for item in candidates
            if item.retention >= min_retention and item.layer in allowed_layers
        ]

        final_results = filtered[:top_k]
        for item in final_results:
            self._l6.track_access(item.memory_id, item.layer)

        elapsed_ms = (time.monotonic() - t0) * 1000
        total_scanned = sum(source_breakdown.values())

        return SearchResult(
            results=final_results,
            total_scanned=total_scanned,
            timing_ms=elapsed_ms,
            source_breakdown=source_breakdown,
        )

    def consolidate(self) -> ConsolidationReport:
        """Run a consolidation cycle: decay, replay, semantic extraction, reviews.

        Applies layer-specific retention decay, replays a sample of L2 episodes
        through the offline semantic extractor, upserts triples into L3, and
        schedules reviews for important low-retention memories.  No external
        LLM key is required.
        """
        engine = ConsolidationEngine(
            self._db,
            self._l2,
            self._l3,
            l4=self._l4,
            config=self._config,
        )
        return engine.run_consolidation_cycle()

    def forget(
        self,
        memory_id: str | None = None,
        *,
        force: bool = False,
    ) -> ForgetResult:
        """Forget one memory or run a global deletable-memory scan.

        When *memory_id* is provided, only that memory is considered.  When
        ``memory_id`` is ``None``, every row with ``status='deletable'`` is
        processed (and, when *force* is ``True``, active rows below the layer
        delete threshold are included as well).

        L2 memories below the archive threshold are moved to L4 when possible;
        otherwise they are marked ``deleted``.  Archived L4 rows purge the gzip
        artifact.  L3 rows are marked ``deleted`` and removed from the vector
        index.

        Parameters
        ----------
        memory_id:
            Target memory identifier, or ``None`` for a global scan.
        force:
            When ``True``, forget eligible memories even if they are still
            ``active`` (below the layer delete threshold).  When ``False``,
            only ``deletable`` rows (or a single memory below threshold) are
            affected.

        Returns
        -------
        ForgetResult
            Structured counts and per-memory actions.
        """
        if memory_id is not None:
            rows = self._fetch_memory_rows(memory_id=memory_id)
        elif force:
            rows = self._fetch_memory_rows(global_forget=True, include_active=True)
        else:
            rows = self._fetch_memory_rows(global_forget=True, include_active=False)

        details: list[dict] = []
        forgotten = 0
        archived = 0
        affected_layers: set[int] = set()
        freed_bytes = 0

        for row in rows:
            action, layer, nbytes = self._forget_one_row(row, force=force)
            if action is None:
                continue
            details.append({"memory_id": row["id"], "action": action})
            affected_layers.add(layer)
            freed_bytes += nbytes
            if action == "archived":
                archived += 1
            elif action == "deleted":
                forgotten += 1

        return ForgetResult(
            forgotten_count=forgotten,
            archived_count=archived,
            freed_memory_mb=freed_bytes / (1024 * 1024),
            affected_layers=sorted(affected_layers),
            details=details,
        )

    def get_retention_curve(
        self,
        layer: int = 2,
        *,
        memory_id: str | None = None,
        days: list[int] | None = None,
    ) -> RetentionCurve:
        """Return predicted retention samples for L2 or L3 decay curves.

        Parameters
        ----------
        layer:
            Memory layer index: ``2`` for episodic (biexponential), ``3`` for
            semantic (power-law).  Ignored when *memory_id* is provided.
        memory_id:
            When provided, build the curve for that memory's layer and
            ``initial_strength`` from ``memory_index``.
        days:
            Optional sorted day offsets to sample; defaults to
            ``[1, 3, 7, 14, 30, 60, 90]``.
        """
        if memory_id is not None:
            rows = self._db.query(
                """
                SELECT layer, initial_strength
                FROM   memory_index
                WHERE  id = ?
                """,
                (memory_id,),
            )
            if not rows:
                raise ValueError(f"memory_id not found: {memory_id!r}")
            mem_layer = int(rows[0]["layer"])
            strength = float(rows[0]["initial_strength"])
            if mem_layer not in (2, 3):
                raise ValueError(
                    f"per-memory retention curves require layer 2 or 3, got {mem_layer}"
                )
            return predict_memory_retention_curve(
                layer=mem_layer,
                initial_strength=strength,
                config=self._config,
                days=days,
            )

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

    def agent_context(self) -> AgentContext:
        """Return a stable :class:`~hm_arch.context.AgentContext` for this store."""
        return AgentContext(self)

    @contextmanager
    def context(self) -> Iterator["HMArch"]:
        """Save and restore L1 working-memory session state.

        On entry, a snapshot of the current L1 store is taken.  On exit (even
        when an exception is raised), L1 is restored to that snapshot so
        ephemeral session additions inside the block do not leak into the
        outer agent turn.  L2/L3 persisted data is unaffected.

        For explicit cross-restart persistence, use
        :meth:`AgentContext.save_session` and :meth:`AgentContext.load_session`.

        Examples
        --------
        ::

            memory.add("baseline context")
            with memory.context():
                memory.add("temporary task note")
            # L1 is back to the pre-block snapshot; L2 still has both adds.
        """
        with self.agent_context():
            yield self

    # ------------------------------------------------------------------
    # Forgetting helpers
    # ------------------------------------------------------------------

    def _fetch_memory_rows(
        self,
        *,
        memory_id: str | None = None,
        global_forget: bool = False,
        include_active: bool = False,
    ) -> list[dict]:
        if memory_id is not None:
            return self._db.query(
                """
                SELECT mi.id,
                       mi.layer,
                       mi.status,
                       mi.current_retention,
                       mi.importance,
                       mi.metadata,
                       mi.created_at,
                       mi.updated_at,
                       e.content AS episode_content
                FROM   memory_index mi
                LEFT JOIN episodes e ON e.memory_id = mi.id
                WHERE  mi.id = ?
                  AND  mi.status != 'deleted'
                """,
                (memory_id,),
            )

        if not global_forget:
            return []

        if include_active:
            cfg = self._config
            return self._db.query(
                """
                SELECT mi.id,
                       mi.layer,
                       mi.status,
                       mi.current_retention,
                       mi.importance,
                       mi.metadata,
                       mi.created_at,
                       mi.updated_at,
                       e.content AS episode_content
                FROM   memory_index mi
                LEFT JOIN episodes e ON e.memory_id = mi.id
                WHERE  mi.status IN ('deletable', 'active', 'archived')
                  AND  mi.layer IN (2, 3, 4)
                  AND  (
                        mi.status = 'deletable'
                     OR mi.status = 'archived'
                     OR (mi.layer = 2 AND mi.current_retention < ?)
                     OR (mi.layer = 3 AND mi.current_retention < ?)
                  )
                """,
                (cfg.l2_delete_threshold, cfg.l3_delete_threshold),
            )

        return self._db.query(
            """
            SELECT mi.id,
                   mi.layer,
                   mi.status,
                   mi.current_retention,
                   mi.importance,
                   mi.metadata,
                   mi.created_at,
                   mi.updated_at,
                   e.content AS episode_content
            FROM   memory_index mi
            LEFT JOIN episodes e ON e.memory_id = mi.id
            WHERE  mi.status = 'deletable'
            """
        )

    def _is_eligible_for_forget(self, row: dict, *, force: bool) -> bool:
        row = dict(row)
        status = row["status"]
        layer = int(row["layer"])
        retention = float(row["current_retention"])

        if status == "deleted":
            return False
        if force:
            return status in ("active", "deletable", "archived")
        if status == "deletable" or status == "archived":
            return True
        if status != "active":
            return False
        threshold = _delete_threshold_for_layer(layer, self._config)
        return retention < threshold

    def _forget_one_row(
        self, row: dict, *, force: bool
    ) -> tuple[str | None, int, int]:
        """Forget a single memory row.

        Returns ``(action, layer, freed_bytes)`` where *action* is
        ``"archived"``, ``"deleted"``, or ``None`` when skipped.
        """
        row = dict(row)
        if not self._is_eligible_for_forget(row, force=force):
            return None, int(row["layer"]), 0

        mid = row["id"]
        layer = int(row["layer"])
        retention = float(row["current_retention"])
        nbytes = len((row.get("episode_content") or "").encode("utf-8"))

        if layer == 2 and row["status"] == "active" and not force:
            archive_thresh = _archive_threshold_for_layer(2, self._config)
            if retention < archive_thresh and self._archive_l2_for_forget(row):
                return "archived", 4, nbytes

        if layer == 4 or row["status"] == "archived":
            purge = self._l4.purge(mid)
            if purge.removed:
                nbytes += 1024
            self._mark_memory_deleted(mid)
            return "deleted", 4, nbytes

        if layer == 2:
            self._l2.remove_from_vector_index(mid)
            self._db.execute("DELETE FROM episodes WHERE memory_id = ?", (mid,))
        elif layer == 3:
            self._l3.remove_from_vector_index(mid)
            self._db.execute("DELETE FROM semantics WHERE memory_id = ?", (mid,))

        self._db.execute("DELETE FROM review_queue WHERE memory_id = ?", (mid,))
        self._mark_memory_deleted(mid)
        self._remove_l1_by_id(mid)
        return "deleted", layer, nbytes

    def _archive_l2_for_forget(self, row: dict) -> bool:
        content = row.get("episode_content")
        if not content:
            ep = self._db.query(
                "SELECT content FROM episodes WHERE memory_id = ?",
                (row["id"],),
            )
            if not ep:
                return False
            content = ep[0]["content"]

        metadata = json.loads(row["metadata"] or "{}")
        metadata["source_l2_memory_id"] = row["id"]
        created_at = _parse_iso_timestamp(row["created_at"])
        updated_raw = row.get("updated_at")
        updated_at = (
            _parse_iso_timestamp(updated_raw) if updated_raw else None
        )

        self._l4.archive(
            row["id"],
            content,
            layer=2,
            created_at=created_at,
            updated_at=updated_at,
            retention=float(row["current_retention"]),
            importance=float(row["importance"]),
            metadata=metadata,
        )

        now_str = datetime.now(tz=timezone.utc).isoformat()
        self._db.execute(
            """
            UPDATE memory_index
               SET status     = 'archived',
                   layer      = 4,
                   metadata   = ?,
                   updated_at = ?
             WHERE id = ?
            """,
            (json.dumps(metadata), now_str, row["id"]),
        )
        self._l2.remove_from_vector_index(row["id"])
        return True

    def _mark_memory_deleted(self, memory_id: str) -> None:
        now_str = datetime.now(tz=timezone.utc).isoformat()
        self._db.execute(
            """
            UPDATE memory_index
               SET status = 'deleted', updated_at = ?
             WHERE id = ?
            """,
            (now_str, memory_id),
        )

    def _remove_l1_by_id(self, memory_id: str) -> None:
        remaining = [
            item
            for item in self._l1.snapshot()
            if item.memory_id != memory_id
        ]
        if len(remaining) != self._l1.size:
            self._l1.load_snapshot(remaining)

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
