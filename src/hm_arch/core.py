"""HMArch — public facade for the HM-Arch memory SDK.

Wires together L0–L6 into a single ergonomic interface: sensory register,
working memory, episodic buffer, semantic memory, long-term archive,
procedural skills, and meta-memory policies.  Persistence uses SQLite with a
local deterministic vector fallback so the facade works fully offline without
any external API keys.

Scoring formula::

    score = retention × relevance × layer_priority

where *layer_priority* comes from :attr:`MemoryConfig.layer_priorities`.

Usage example::

    from hm_arch import HMArch, EventType

    memory = HMArch(db_path=":memory:")
    memory.add("用户偏好 Python", event_type=EventType.CONVERSATION)
    results = memory.search("用户喜欢什么语言", top_k=10)
    report = memory.consolidate()
    curve = memory.get_retention_curve(layer=2)
"""

from __future__ import annotations

import json
import math
import time
from contextlib import contextmanager
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator, Optional, Union

from .config import MemoryConfig
from .provenance import build_provenance, parse_provenance_row
from .consolidation.replay import ConsolidationEngine, SemanticExtractor
from .providers import create_vector_store, resolve_llm_provider
from .providers.semantic import ProviderSemanticExtractor
from .context import AgentContext
from .forgetting.controller import ForgettingController
from .forgetting.decay import (
    _DEFAULT_DAYS,
    predict_memory_retention_curve,
    predict_retention_curve,
)
from .forgetting.strength import (
    StrengthFactors,
    apply_retrieval_reinforcement,
    compute_initial_strength,
    count_l2_repetitions,
    merge_metadata_with_strength,
    score_local_emotion,
    score_local_importance,
    strength_bounds,
)
from .forgetting.time import SystemTimeProvider, TimeProvider
from .layers.base import LayerItem
from .layers.l0_sensory import L0SensoryRegister
from .layers.l1_working import L1WorkingMemory
from .layers.l2_episodic import L2EpisodicBuffer
from .layers.l3_semantic import L3SemanticMemory
from .layers.l4_ltm import L4EpisodicLTM
from .layers.l5_procedural import L5ProceduralMemory, SkillRecord
from .layers.l6_meta import HotMemoryRecord, L6MetaMemory, StrategyPlan
from .layers.l6_meta import _parse_hot_access_threshold
from .safety.sensitive_data import (
    filter_metadata_values,
    filter_sensitive_content,
    merge_diagnostics,
)
from .storage.sqlite import SQLiteStore
from .storage.vector import _token_overlap_score, _tokenize
from .types import (
    ConsolidationReport,
    EventType,
    ForgetResult,
    MemoryItem,
    MemoryProvenance,
    MemoryReceipt,
    MemoryStats,
    RetentionCurve,
    SearchResult,
)

__all__ = ["HMArch", "AgentContext"]

_DEFAULT_SEARCH_LAYERS: tuple[int, ...] = (0, 1, 2, 3, 4)
_HOT_MEMORY_SCORE_BOOST: float = 1.25


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


def _days_up_to(days_ahead: int) -> list[int]:
    """PRD day checkpoints capped by *days_ahead*."""
    if days_ahead < 1:
        raise ValueError(f"days_ahead must be >= 1, got {days_ahead}")
    days = [d for d in _DEFAULT_DAYS if d <= days_ahead]
    if days_ahead not in days:
        days.append(days_ahead)
    return sorted(days)


def _archive_storage_mb(l4: L4EpisodicLTM) -> float:
    """Return total on-disk size of L4 gzip archives in megabytes."""
    total_bytes = sum(entry.compressed_bytes for entry in l4.list_archives())
    return total_bytes / (1024 * 1024)


def _l4_index_count(db: SQLiteStore) -> int:
    rows = db.query(
        """
        SELECT COUNT(*) AS n
        FROM   memory_index
        WHERE  layer = 4 AND status = 'archived'
        """
    )
    return int(rows[0]["n"]) if rows else 0


def _l6_persisted_count(db: SQLiteStore) -> int:
    """Count L6-owned rows in ``meta_memory`` (policies, access tallies, totals)."""
    rows = db.query(
        """
        SELECT COUNT(*) AS n
        FROM   meta_memory
        WHERE  key LIKE 'hm_arch.l6.%'
        """
    )
    return int(rows[0]["n"]) if rows else 0


def _parse_policy_float(raw: str, default: float) -> float:
    try:
        return float(raw)
    except ValueError:
        return default


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


def _load_provenance(
    db: SQLiteStore,
    memory_id: str,
    *,
    fallback_memory_type: str | None = None,
) -> MemoryProvenance | None:
    rows = db.query(
        """
        SELECT created_at,
               provenance_agent,
               provenance_project,
               provenance_session,
               memory_type,
               metadata
        FROM   memory_index
        WHERE  id = ?
        """,
        (memory_id,),
    )
    if not rows:
        return None
    return parse_provenance_row(rows[0], fallback_memory_type=fallback_memory_type)


def _provenance_for_item_metadata(
    db: SQLiteStore,
    metadata: dict,
    *,
    fallback_memory_type: str | None = None,
) -> MemoryProvenance | None:
    source_id = metadata.get("source_l2_memory_id")
    if isinstance(source_id, str) and source_id:
        return _load_provenance(
            db,
            source_id,
            fallback_memory_type=fallback_memory_type,
        )
    return None


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
        results = memory.search("用户喜欢什么语言", top_k=10)
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
        *,
        time_provider: Optional[TimeProvider] = None,
    ) -> None:
        """Create an :class:`HMArch` memory store.

        Parameters
        ----------
        db_path:
            SQLite database path.  Ignored when *config* is supplied.
        config:
            Optional runtime configuration.
        time_provider:
            Injectable clock for deterministic lifecycle tests.  Defaults to
            :class:`~hm_arch.forgetting.time.SystemTimeProvider`.
        """
        if config is None:
            config = MemoryConfig(db_path=db_path)
        self._config = config
        self._time = time_provider or SystemTimeProvider()

        self._db = SQLiteStore(
            self._config.db_path,
            busy_timeout_ms=self._config.sqlite_busy_timeout_ms,
            lock_retries=self._config.sqlite_lock_retries,
            lock_retry_base_delay_s=self._config.sqlite_lock_retry_base_delay_s,
        )
        self._db.connect()
        self._db.initialize_schema()

        self._llm = resolve_llm_provider(self._config)
        l2_vector = create_vector_store(self._config, collection="l2_episodic")
        l3_vector = create_vector_store(self._config, collection="l3_semantic")

        self._l0 = L0SensoryRegister(capacity=self._config.l0_capacity)
        self._l1 = L1WorkingMemory()
        self._l2 = L2EpisodicBuffer(
            self._db,
            vector_store=l2_vector,
            time_provider=self._time,
        )
        self._l3 = L3SemanticMemory(
            self._db,
            max_memories=self._config.max_memories_l3,
            config=self._config,
            vector_store=l3_vector,
            time_provider=self._time,
        )
        self._l4 = L4EpisodicLTM(_resolve_archive_root(self._config))
        self._l5 = L5ProceduralMemory(
            self._db, max_skills=self._config.max_skills_l5
        )
        self._l6 = L6MetaMemory(self._db)

        self._forgetting = ForgettingController(
            self._db,
            self._config,
            time_provider=self._time,
            consolidate_fn=self.consolidate,
            forget_fn=lambda memory_id: self.forget(memory_id),
        )
        self._sensitive_filter_stats: dict[str, int] = {"truncations": 0, "filtered_adds": 0}

    # ------------------------------------------------------------------
    # Primary public interface
    # ------------------------------------------------------------------

    def add(
        self,
        content: str,
        event_type: EventType = EventType.CONVERSATION,
        metadata: Optional[dict] = None,
        importance: Optional[float] = None,
        *,
        agent: str | None = None,
        project: str | None = None,
        session: str | None = None,
    ) -> MemoryReceipt:
        """Store *content* in L0, L1, and the episodic buffer (L2).

        ``add()`` always succeeds without an external LLM key when capacity
        limits allow.  L3 semantic extraction is **not** triggered here; it
        happens during ``consolidate()``.

        Parameters
        ----------
        content:
            Text to remember.
        event_type:
            Classification for the event; defaults to
            :attr:`~hm_arch.types.EventType.CONVERSATION`.
        metadata:
            Optional key/value pairs attached to the memory record.
        importance:
            Importance score in ``[0, 1]``.  When omitted the L2 layer
            default (``0.5``) is applied.
        agent:
            Optional agent name recorded as provenance.
        project:
            Optional project path or identifier recorded as provenance.
        session:
            Optional host-agent session identifier recorded as provenance.

        Returns
        -------
        MemoryReceipt
            Confirmation including the ``memory_id`` assigned by L2, which
            is the durable database-backed identifier for the event.
        """
        if self._l2.count() >= self._config.max_memories_l2:
            raise ValueError(
                f"max_memories_l2 limit ({self._config.max_memories_l2}) reached"
            )

        content_result = filter_sensitive_content(content, self._config)
        filtered_metadata, metadata_diag = filter_metadata_values(
            metadata, self._config
        )
        filter_diag = merge_diagnostics(content_result.diagnostics, metadata_diag)
        content = content_result.content
        metadata = filtered_metadata

        if filter_diag.was_modified:
            self._sensitive_filter_stats["filtered_adds"] += 1
            if filter_diag.truncated:
                self._sensitive_filter_stats["truncations"] += 1
            for category, count in filter_diag.redactions_by_category.items():
                key = f"redactions.{category}"
                self._sensitive_filter_stats[key] = (
                    self._sensitive_filter_stats.get(key, 0) + count
                )

        strength_min, strength_max, retrieval_inc, _ = strength_bounds(self._config)
        if importance is not None:
            imp = importance
        elif self._config.enable_llm_providers:
            imp = self._llm.score_importance(
                content,
                event_type=event_type.value,
                metadata=metadata,
            )
        else:
            imp = score_local_importance(
                content, event_type=event_type, metadata=metadata
            )
        emotion = score_local_emotion(content, event_type=event_type)
        repetition = count_l2_repetitions(self._db, content)
        factors = StrengthFactors(
            importance=imp,
            emotion=emotion,
            encode_repetitions=repetition,
        )
        strength = compute_initial_strength(
            importance=factors.importance,
            emotion=factors.emotion,
            encode_repetitions=factors.encode_repetitions,
            successful_retrievals=factors.successful_retrievals,
            consistency=factors.consistency,
            strength_min=strength_min,
            strength_max=strength_max,
            retrieval_increment=retrieval_inc,
        )
        merged_meta = merge_metadata_with_strength(metadata, factors)
        if filter_diag.was_modified:
            merged_meta = dict(merged_meta)
            merged_meta["sensitive_filter"] = filter_diag.to_metadata()
        provenance = build_provenance(
            agent=agent,
            project=project,
            session=session,
            memory_type=event_type.value,
            created_at=self._time.now(),
        )

        # L2 episodic buffer — persisted to SQLite, survives restarts
        l2_mid = self._l2.encode(
            content,
            event_type=event_type,
            metadata=merged_meta,
            importance=imp,
            emotion_score=emotion,
            initial_strength=strength,
            strength_max=strength_max,
            provenance=provenance,
        )

        l0_meta = dict(metadata) if metadata is not None else {}
        l0_meta["source_l2_memory_id"] = l2_mid
        self._l0.add(content, metadata=l0_meta)

        # L1 uses the same memory_id as L2 so forget() can remove both layers
        self._l1.add(content, metadata=metadata, memory_id=l2_mid)

        sample_days = [1, 7, 30]
        curve = predict_memory_retention_curve(
            layer=2,
            initial_strength=strength,
            config=self._config,
            days=sample_days,
        )
        decay_estimate = {
            f"{d}d": curve.retention[i] for i, d in enumerate(curve.days)
        }
        receipt = MemoryReceipt(
            memory_id=l2_mid,
            layer=2,
            importance=imp,
            initial_strength=strength,
            decay_estimate=decay_estimate,
            consolidation_scheduled=self._time.now(),
            provenance=provenance,
            sensitive_filter=(
                filter_diag.to_metadata() if filter_diag.was_modified else None
            ),
        )
        self._run_lifecycle_tick()
        return receipt

    def search(
        self,
        query: str,
        top_k: int = 10,
        *,
        min_retention: float = 0.1,
        layer_filter: list[int] | None = None,
    ) -> SearchResult:
        """Return the top-*k* memories most relevant to *query*.

        Queries L0 sensory register, L1 working memory, L2 episodic buffer,
        L3 semantic memory, and L4 archived episodic memories.  Candidates from
        all layers are merged,
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
            return.  Defaults to ``10`` (PRD).
        min_retention:
            Exclude hits whose retention is strictly below this value.
            Defaults to ``0.1`` (PRD).
        layer_filter:
            When provided, only search these layer indices (e.g. ``[1, 2, 3]``).
            When ``None``, all supported layers ``(0, 1, 2, 3, 4)`` are queried.

        L6 policies ``retrieval_top_k_multiplier`` and ``prefer_hot_memories``
        adjust the effective *top_k* and ranking scores when configured.

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

        effective_top_k = self._effective_search_top_k(top_k)
        self._forgetting.set_context_query(query)

        t0 = time.monotonic()
        priorities = self._config.layer_priorities

        candidates: list[MemoryItem] = []
        source_breakdown: dict[int, int] = {0: 0, 1: 0, 2: 0, 3: 0, 4: 0}

        # ---- L0: sensory register ----------------------------------------
        l0_hits = (
            self._l0.retrieve(query, top_k=effective_top_k)
            if 0 in allowed_layers
            else []
        )
        source_breakdown[0] = len(l0_hits)
        l0_priority = priorities.get("L0", 1.0)
        for item in l0_hits:
            if not self._l0_searchable(item):
                continue
            rel = _relevance(query, item.content)
            score = 1.0 * rel * l0_priority
            candidates.append(
                MemoryItem(
                    memory_id=item.memory_id,
                    layer=0,
                    content=item.content,
                    retention=1.0,
                    relevance=rel,
                    score=score,
                    metadata=item.metadata,
                    provenance=_provenance_for_item_metadata(self._db, item.metadata),
                )
            )

        # ---- L1: in-memory working memory --------------------------------
        # Pull up to top_k candidates from each layer; the merged pool is
        # then re-ranked by the combined score formula.
        l1_hits = (
            self._l1.retrieve(query, top_k=effective_top_k)
            if 1 in allowed_layers
            else []
        )
        source_breakdown[1] = len(l1_hits)
        l1_priority = priorities.get("L1", 0.9)
        for item in l1_hits:
            if not self._l1_searchable(item.memory_id):
                continue
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
                    provenance=_load_provenance(self._db, item.memory_id),
                )
            )

        # ---- L2: episodic buffer -----------------------------------------
        l2_hits = (
            self._l2.retrieve(query, top_k=effective_top_k)
            if 2 in allowed_layers
            else []
        )
        source_breakdown[2] = len(l2_hits)
        l2_priority = priorities.get("L2", 0.7)
        for item in l2_hits:
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
                    provenance=item.provenance,
                )
            )

        # ---- L3: semantic memory -----------------------------------------
        l3_hits = (
            self._l3.search(query, top_k=effective_top_k)
            if 3 in allowed_layers
            else []
        )
        source_breakdown[3] = len(l3_hits)
        l3_priority = priorities.get("L3", 0.8)
        for item in l3_hits:
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
                    provenance=item.provenance,
                )
            )

        # ---- L4: archived episodic long-term memory ----------------------
        l4_hits = (
            self._l4.search(query, top_k=effective_top_k)
            if 4 in allowed_layers
            else []
        )
        source_breakdown[4] = len(l4_hits)
        l4_priority = priorities.get("L4", 0.5)
        for hit in l4_hits:
            record = hit.record
            archived_rows = self._db.query(
                """
                SELECT id FROM memory_index
                WHERE id = ? AND status = 'archived' AND layer = 4
                """,
                (record.memory_id,),
            )
            if not archived_rows:
                continue
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
                    provenance=_load_provenance(
                        self._db,
                        record.memory_id,
                        fallback_memory_type="archived",
                    ),
                )
            )

        # When L1/L2 share a memory_id, keep the higher-layer (persisted) item
        by_id: dict[str, MemoryItem] = {}
        for item in candidates:
            prev = by_id.get(item.memory_id)
            if prev is None or item.layer > prev.layer:
                by_id[item.memory_id] = item
        candidates = list(by_id.values())
        candidates = self._apply_hot_memory_boost(candidates)

        # Sort descending by score; stable sort preserves layer order as tiebreak
        candidates.sort(key=lambda x: -x.score)

        filtered = [
            item
            for item in candidates
            if item.layer in allowed_layers
            and (item.layer in (0, 4) or item.retention >= min_retention)
        ]

        final_results = filtered[:effective_top_k]
        reinforce_targets: dict[str, float] = {}
        for item in final_results:
            self._l6.track_access(item.memory_id, item.layer)
            reinforce_id = item.memory_id
            if item.layer in (0, 1):
                linked = item.metadata.get("source_l2_memory_id")
                if isinstance(linked, str) and linked:
                    reinforce_id = linked
            if item.layer in (2, 3) or reinforce_id != item.memory_id:
                prev = reinforce_targets.get(reinforce_id, 0.0)
                reinforce_targets[reinforce_id] = max(prev, item.relevance)
        for memory_id, relevance in reinforce_targets.items():
            self._reinforce_after_retrieval(memory_id, relevance)

        elapsed_ms = (time.monotonic() - t0) * 1000
        total_scanned = sum(source_breakdown.values())

        self._run_lifecycle_tick()

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
        consolidation_config = self._consolidation_config()
        if self._config.enable_llm_providers:
            extractor: SemanticExtractor | ProviderSemanticExtractor = (
                ProviderSemanticExtractor(
                    self._llm,
                    fallback_to_local=self._config.provider_fallback_to_local,
                )
            )
        else:
            extractor = SemanticExtractor()
        engine = ConsolidationEngine(
            self._db,
            self._l2,
            self._l3,
            l4=self._l4,
            config=consolidation_config,
            extractor=extractor,
            time_provider=self._time,
        )
        return engine.run_consolidation_cycle()

    def run_lifecycle(self) -> None:
        """Run one automatic lifecycle tick.

        Applies due auto-consolidation (when enabled) and conservative
        physical cleanup for score-qualified ``deletable`` rows past
        ``deletion_safety_period_hours``.
        """
        self._run_lifecycle_tick()

    def _run_lifecycle_tick(self) -> None:
        self._forgetting.run_lifecycle_tick()

    def _reinforce_after_retrieval(self, memory_id: str, relevance: float) -> None:
        """Boost PRD ``R_mod`` after a successful search hit (L2/L3)."""
        apply_retrieval_reinforcement(
            self._db,
            memory_id,
            relevance,
            config=self._config,
            time_provider=self._time,
        )

    def forget(
        self,
        memory_id: str | None = None,
        *,
        force: bool = False,
    ) -> ForgetResult:
        """Forget one memory or run a context-aware global forgetting scan.

        When *memory_id* is provided, only that memory is considered.  When
        ``memory_id`` is ``None``, eligible rows are evaluated with the PRD
        context-aware forgetting score (retention, relevance, redundancy,
        contradiction, privacy).  Only candidates whose composite score meets
        ``config.forgetting_score_threshold`` are removed.

        With ``memory_id is None`` and ``force=False``, only ``deletable`` rows
        are scanned.  With ``force=True``, active rows below the layer delete
        threshold are included as well.  Automated lifecycle physical cleanup
        still waits for ``deletion_safety_period_hours``; this method performs
        immediate removal for score-qualified candidates.

        L2 memories below the archive threshold are moved to L4 when possible;
        otherwise they are marked ``deleted``.  Archived L4 rows purge the gzip
        artifact.  L3 rows are marked ``deleted`` and removed from the vector
        index.

        Parameters
        ----------
        memory_id:
            Target memory identifier, or ``None`` for a global scan.
        force:
            When ``True``, include active low-retention rows in the global scan.

        Returns
        -------
        ForgetResult
            Structured counts and per-memory actions.
        """
        if memory_id is not None:
            rows = self._fetch_memory_rows(memory_id=memory_id)
            use_context_gate = False
        elif force:
            rows = self._fetch_memory_rows(global_forget=True, include_active=True)
            use_context_gate = True
        else:
            rows = self._fetch_memory_rows(global_forget=True, include_active=False)
            use_context_gate = True

        details: list[dict] = []
        forgotten = 0
        archived = 0
        affected_layers: set[int] = set()
        freed_bytes = 0

        for row in rows:
            record = dict(row)
            if use_context_gate and not self._forgetting.is_forget_candidate(
                record, require_safety_period=False
            ):
                continue

            action, layer, nbytes = self._forget_one_row(record, force=force)
            if action is None:
                continue
            details.append({"memory_id": record["id"], "action": action})
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
        layer_or_memory_id: Union[int, str] = 2,
        days_ahead: int = 90,
        *,
        layer: int | None = None,
        memory_id: str | None = None,
        days: list[int] | None = None,
    ) -> RetentionCurve:
        """Return predicted retention samples for L2 or L3 decay curves.

        Supports the PRD positional form ``get_retention_curve(memory_id,
        days_ahead=90)`` as well as the layer-based form
        ``get_retention_curve(layer=2)``.

        Parameters
        ----------
        layer_or_memory_id:
            When an ``int`` in ``(2, 3)``, selects the layer decay curve.
            When a ``str``, treated as *memory_id* (PRD positional call).
        days_ahead:
            Maximum day offset to sample when building the default day list.
            Ignored when *days* is provided.
        layer:
            Keyword-only layer index (overrides *layer_or_memory_id* when set).
        memory_id:
            Keyword-only memory identifier (overrides *layer_or_memory_id*).
        days:
            Optional sorted day offsets to sample; defaults to PRD checkpoints
            up to *days_ahead*.
        """
        resolved_memory_id: str | None = memory_id
        resolved_layer: int | None = layer

        if resolved_memory_id is None and isinstance(layer_or_memory_id, str):
            resolved_memory_id = layer_or_memory_id
        elif resolved_layer is None and isinstance(layer_or_memory_id, int):
            resolved_layer = layer_or_memory_id

        if resolved_layer is None and resolved_memory_id is None:
            resolved_layer = 2

        sample_days = days if days is not None else _days_up_to(days_ahead)

        if resolved_memory_id is not None:
            rows = self._db.query(
                """
                SELECT layer, initial_strength
                FROM   memory_index
                WHERE  id = ?
                """,
                (resolved_memory_id,),
            )
            if not rows:
                raise ValueError(f"memory_id not found: {resolved_memory_id!r}")
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
                days=sample_days,
            )

        assert resolved_layer is not None
        return predict_retention_curve(
            layer=resolved_layer,
            config=self._config,
            days=sample_days,
        )

    def get_stats(self) -> MemoryStats:
        """Return aggregated statistics about the memory store.

        Counts include in-session L0/L1 items, persisted L2/L3 active rows,
        archived L4 index rows, L5 skills, and L6 persisted ``meta_memory`` rows.
        Retention histogram buckets are computed from ``memory_index`` for
        active persisted memories.  :attr:`~MemoryStats.archive_storage_mb`
        reports on-disk L4 gzip usage.
        """
        by_layer = {
            0: self._l0.size,
            1: self._l1.size,
            2: self._l2.count(),
            3: self._l3.count(status="active"),
            4: _l4_index_count(self._db),
            5: self._l5.count(),
            6: _l6_persisted_count(self._db),
        }
        total_memories = sum(by_layer.values())

        retention_distribution = _retention_histogram(self._db)
        review_queue_length = _review_queue_length(self._db)
        last_consolidation_at = _last_consolidation_at(self._db)
        storage_size_mb = _database_size_mb(self._db)
        archive_storage_mb = _archive_storage_mb(self._l4)

        return MemoryStats(
            total_memories=total_memories,
            by_layer=by_layer,
            storage_size_mb=storage_size_mb,
            retention_distribution=retention_distribution,
            review_queue_length=review_queue_length,
            last_consolidation_at=last_consolidation_at,
            archive_storage_mb=archive_storage_mb,
            sensitive_data_diagnostics=dict(self._sensitive_filter_stats),
        )

    # ------------------------------------------------------------------
    # L5 procedural memory (public facade)
    # ------------------------------------------------------------------

    def store_skill(
        self,
        name: str,
        *,
        description: str | None = None,
        code: str | None = None,
    ) -> SkillRecord:
        """Persist or update a procedural skill in L5."""
        return self._l5.store_skill(name, description=description, code=code)

    def match_skill(
        self, query: str, *, record_usage: bool = True
    ) -> SkillRecord | None:
        """Return the best-matching L5 skill for *query*, or ``None``."""
        return self._l5.match_skill(query, record_usage=record_usage)

    def list_skills(self) -> list[SkillRecord]:
        """Return all L5 skills sorted by name."""
        return self._l5.list_skills()

    def record_skill_result(
        self,
        skill_id_or_name: str,
        success: bool,
        *,
        duration_ms: float | None = None,
    ) -> SkillRecord:
        """Record the outcome of applying an L5 skill."""
        return self._l5.record_skill_result(
            skill_id_or_name, success, duration_ms=duration_ms
        )

    def get_skill(self, skill_id_or_name: str) -> SkillRecord | None:
        """Return an L5 skill by id or name without matching."""
        return self._l5.get_skill(skill_id_or_name)

    # ------------------------------------------------------------------
    # L6 meta memory (public facade)
    # ------------------------------------------------------------------

    def set_policy(self, name: str, value: str) -> None:
        """Persist an L6 policy that tunes retrieval or consolidation."""
        self._l6.set_policy(name, value)

    def get_policy(self, name: str) -> str:
        """Return an L6 policy value (built-in default when unset)."""
        return self._l6.get_policy(name)

    def get_hot_memories(
        self, limit: int = 10, *, layer: int | None = None
    ) -> list[HotMemoryRecord]:
        """Return frequently accessed memories tracked by L6."""
        return self._l6.get_hot_memories(limit, layer=layer)

    def strategy_plan(self) -> StrategyPlan:
        """Return current L6 policies and deterministic recommendations."""
        return self._l6.strategy_plan()

    def agent_context(self) -> AgentContext:
        """Return a stable :class:`~hm_arch.context.AgentContext` for this store."""
        return AgentContext(self)

    @contextmanager
    def context(self) -> Iterator[AgentContext]:
        """Save and restore L1 working-memory session state.

        Yields an :class:`~hm_arch.context.AgentContext` so callers can use the
        PRD pattern ``with memory.context() as ctx: ctx.load_session(); ...;
        ctx.save_session()``.  On exit, L1 is rolled back to the pre-block
        snapshot (even when an exception is raised).  L2/L3 persisted data is
        unaffected.

        Existing integrations may keep using the outer ``memory`` variable for
        ``add()`` / ``search()`` inside the block.

        Examples
        --------
        ::

            memory.add("baseline context")
            with memory.context() as ctx:
                ctx.load_session()
                memory.add("temporary task note")
                ctx.save_session()
            # L1 is back to the pre-block snapshot; L2 still has both adds.
        """
        ctx = self.agent_context()
        saved_l1 = self._l1.snapshot()
        try:
            yield ctx
        finally:
            self._l1.load_snapshot(saved_l1)

    # ------------------------------------------------------------------
    # L6 policy helpers
    # ------------------------------------------------------------------

    def _effective_search_top_k(self, top_k: int) -> int:
        multiplier = _parse_policy_float(
            self._l6.get_policy("retrieval_top_k_multiplier"), 1.0
        )
        if multiplier <= 0.0:
            multiplier = 1.0
        return max(1, math.ceil(top_k * multiplier))

    def _apply_hot_memory_boost(self, candidates: list[MemoryItem]) -> list[MemoryItem]:
        if self._l6.get_policy("prefer_hot_memories").lower() != "true":
            return candidates
        threshold = _parse_hot_access_threshold(
            self._l6.get_policy("hot_access_threshold")
        )
        hot_ids = {
            record.memory_id
            for record in self._l6.get_hot_memories(limit=1000)
            if record.access_count >= threshold
        }
        if not hot_ids:
            return candidates
        boosted: list[MemoryItem] = []
        for item in candidates:
            if item.memory_id in hot_ids:
                boosted.append(
                    MemoryItem(
                        memory_id=item.memory_id,
                        layer=item.layer,
                        content=item.content,
                        retention=item.retention,
                        relevance=item.relevance,
                        score=item.score * _HOT_MEMORY_SCORE_BOOST,
                        metadata=item.metadata,
                        provenance=item.provenance,
                    )
                )
            else:
                boosted.append(item)
        return boosted

    def _consolidation_config(self) -> MemoryConfig:
        """Return config for consolidation, honoring only explicit L6 overrides."""
        policy_key = "hm_arch.l6.policy.consolidation_replay_ratio"
        rows = self._db.query(
            "SELECT value FROM meta_memory WHERE key = ?",
            (policy_key,),
        )
        if not rows:
            return self._config
        replay = _parse_policy_float(
            str(rows[0]["value"]), self._config.replay_sample_ratio
        )
        if not 0.0 < replay <= 1.0:
            return self._config
        return replace(self._config, replay_sample_ratio=replay)

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
                   e.content AS episode_content,
                   s.entity,
                   s.relation,
                   s.value,
                   s.entity || ' ' || s.relation || ' ' || s.value AS semantic_content
            FROM   memory_index mi
            LEFT JOIN episodes e ON e.memory_id = mi.id
            LEFT JOIN semantics s ON s.memory_id = mi.id
            WHERE  mi.status IN ('deletable', 'superseded')
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
        if status == "deletable" or status == "archived" or status == "superseded":
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
                self._remove_l1_by_id(mid)
                self._remove_l0_by_l2_id(mid)
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
        self._remove_l0_by_l2_id(mid)
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

    def _l1_searchable(self, memory_id: str) -> bool:
        """Return whether an L1 item should appear in search results."""
        rows = self._db.query(
            "SELECT status FROM memory_index WHERE id = ?",
            (memory_id,),
        )
        if not rows:
            return True
        return rows[0]["status"] == "active"

    def _l0_searchable(self, item: LayerItem) -> bool:
        """Return whether an L0 item should appear in search results."""
        linked = item.metadata.get("source_l2_memory_id")
        if not linked:
            return True
        rows = self._db.query(
            "SELECT status FROM memory_index WHERE id = ?",
            (linked,),
        )
        if not rows:
            return True
        return rows[0]["status"] == "active"

    def _remove_l0_by_l2_id(self, l2_memory_id: str) -> None:
        remaining = [
            item
            for item in self._l0.snapshot()
            if item.metadata.get("source_l2_memory_id") != l2_memory_id
        ]
        if len(remaining) != self._l0.size:
            self._l0.clear()
            for item in remaining:
                self._l0.add(item.content, metadata=dict(item.metadata))

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
