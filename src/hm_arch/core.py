"""HMArch public facade — entry point for the HM-Arch SDK.

Wires together L1 working memory (in-memory), L2 episodic buffer (SQLite),
and L3 semantic memory (SQLite) into a single, easy-to-use interface.

Scoring
-------
Search results are ranked by::

    score = retention * relevance * layer_priority

where *layer_priority* is taken from :attr:`~hm_arch.config.MemoryConfig.layer_priorities`
(default: L1=0.9, L2=0.7, L3=0.8).
"""

from __future__ import annotations

import dataclasses
import math
import time
from datetime import datetime, timedelta, timezone

from .config import MemoryConfig
from .layers.base import _tokenize, _token_overlap_score
from .layers.l1_working import L1WorkingMemory
from .layers.l2_episodic import L2EpisodicBuffer
from .layers.l3_semantic import L3SemanticMemory
from .storage.sqlite import SQLiteStore
from .types import (
    EventType,
    MemoryItem,
    MemoryReceipt,
    SearchResult,
)

__all__ = ["HMArch"]

# Mapping from integer layer index to config priority key string.
_PRIORITY_KEY: dict[int, str] = {1: "L1", 2: "L2", 3: "L3"}


class HMArch:
    """Human-like memory facade for coding agents.

    Combines L1 (in-memory working), L2 (durable episodic), and L3 (durable
    semantic) memory into a single ``add`` / ``search`` API.  No external LLM
    or API key is required for the default offline path.

    Parameters
    ----------
    db_path:
        Path to the SQLite database file.  Use ``":memory:"`` for an
        ephemeral in-process store (useful for testing).  When supplied,
        this overrides ``config.db_path``.
    config:
        Optional :class:`~hm_arch.config.MemoryConfig` instance.  Defaults
        to a fresh default config if omitted.

    Examples
    --------
    ::

        from hm_arch import HMArch, EventType

        memory = HMArch(db_path=":memory:")
        memory.add("用户偏好 Python", event_type=EventType.CONVERSATION)
        results = memory.search("用户偏好")
        for item in results.results:
            print(item.layer, item.score, item.content)
    """

    def __init__(
        self,
        db_path: str | None = None,
        config: MemoryConfig | None = None,
    ) -> None:
        self._config: MemoryConfig = config if config is not None else MemoryConfig()
        if db_path is not None:
            self._config = dataclasses.replace(self._config, db_path=db_path)

        self._db = SQLiteStore(self._config.db_path).connect()
        self._db.initialize_schema()

        self._l1 = L1WorkingMemory()
        self._l2 = L2EpisodicBuffer(self._db)
        self._l3 = L3SemanticMemory(self._db)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def add(
        self,
        content: str,
        event_type: EventType = EventType.OBSERVATION,
        metadata: dict | None = None,
    ) -> MemoryReceipt:
        """Add *content* to memory.

        Writes to L1 (in-memory working memory) and L2 (durable episodic
        buffer) synchronously.  No external LLM is required.

        Parameters
        ----------
        content:
            Text to remember.  CJK characters are fully supported.
        event_type:
            Classification of the event.  Defaults to
            :attr:`~hm_arch.types.EventType.OBSERVATION`.
        metadata:
            Optional key/value pairs stored alongside the memory.

        Returns
        -------
        MemoryReceipt
            Confirmation with the ``memory_id``, layer index, importance,
            initial retention strength, decay estimates, and next
            consolidation time.
        """
        self._l1.add(content, metadata=metadata)
        mid = self._l2.encode(content, event_type=event_type, metadata=metadata)

        importance = self._l2._default_importance
        initial_strength = self._l2._default_initial_strength

        return MemoryReceipt(
            memory_id=mid,
            layer=2,
            importance=importance,
            initial_strength=initial_strength,
            decay_estimate=self._decay_estimate(initial_strength),
            consolidation_scheduled=self._next_consolidation_time(),
        )

    def search(
        self,
        query: str,
        top_k: int = 5,
    ) -> SearchResult:
        """Search all memory layers for content relevant to *query*.

        Candidates from L1 (working), L2 (episodic), and L3 (semantic) are
        collected and ranked by::

            score = retention * relevance * layer_priority

        Results are returned sorted descending by score.

        Parameters
        ----------
        query:
            Free-text search string.  CJK characters are fully supported.
        top_k:
            Maximum number of results to return after ranking.

        Returns
        -------
        SearchResult
            Ranked list of :class:`~hm_arch.types.MemoryItem` objects with
            source layer, scores, and diagnostic metadata.
        """
        t0 = time.perf_counter()
        priorities = self._config.layer_priorities
        items: list[MemoryItem] = []
        source_breakdown: dict[int, int] = {1: 0, 2: 0, 3: 0}

        # --- L1: in-memory working memory -------------------------------
        l1_hits = self._l1.retrieve(query, top_k=top_k)
        source_breakdown[1] = len(l1_hits)
        priority_l1 = priorities.get("L1", 0.9)
        q_tokens = _tokenize(query)
        for li in l1_hits:
            relevance = _token_overlap_score(q_tokens, _tokenize(li.content))
            score = 1.0 * relevance * priority_l1
            items.append(
                MemoryItem(
                    memory_id=li.memory_id,
                    layer=1,
                    content=li.content,
                    retention=1.0,
                    relevance=relevance,
                    score=score,
                    metadata=li.metadata,
                )
            )

        # --- L2: durable episodic buffer --------------------------------
        l2_hits = self._l2.retrieve(query, top_k=top_k)
        source_breakdown[2] = len(l2_hits)
        priority_l2 = priorities.get("L2", 0.7)
        for ep in l2_hits:
            score = ep.retention * ep.relevance * priority_l2
            items.append(
                MemoryItem(
                    memory_id=ep.memory_id,
                    layer=2,
                    content=ep.content,
                    retention=ep.retention,
                    relevance=ep.relevance,
                    score=score,
                    metadata=ep.metadata,
                )
            )

        # --- L3: durable semantic memory --------------------------------
        l3_hits = self._l3.search(query, top_k=top_k)
        source_breakdown[3] = len(l3_hits)
        priority_l3 = priorities.get("L3", 0.8)
        for sf in l3_hits:
            # Retention for L3 is 1.0 until HM-9 forgetting is wired in;
            # all newly upserted triples start with current_retention = 1.0.
            retention = 1.0
            score = retention * sf.relevance * priority_l3
            content = f"{sf.entity} {sf.relation} {sf.value}"
            items.append(
                MemoryItem(
                    memory_id=sf.memory_id,
                    layer=3,
                    content=content,
                    retention=retention,
                    relevance=sf.relevance,
                    score=score,
                    metadata=sf.metadata,
                )
            )

        # Deduplicate by memory_id, keeping the highest-scoring occurrence.
        seen: dict[str, MemoryItem] = {}
        for item in items:
            if item.memory_id not in seen or item.score > seen[item.memory_id].score:
                seen[item.memory_id] = item

        ranked = sorted(seen.values(), key=lambda x: x.score, reverse=True)[:top_k]
        elapsed_ms = (time.perf_counter() - t0) * 1000.0

        return SearchResult(
            results=ranked,
            total_scanned=sum(source_breakdown.values()),
            timing_ms=elapsed_ms,
            source_breakdown=source_breakdown,
        )

    def close(self) -> None:
        """Close the underlying SQLite database connection."""
        self._db.close()

    def __enter__(self) -> "HMArch":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _decay_estimate(self, initial_strength: float) -> dict:
        """Return L2 bi-exponential retention estimates at 1, 7, and 30 days.

        Uses the formula::

            R(t) = S * (w_f * exp(-t/τ_f) + (1 - w_f) * exp(-t/τ_s))

        where *S* is *initial_strength*, *w_f* is ``l2_fast_weight``,
        *τ_f* is ``l2_fast_tau`` (hours), and *τ_s* is ``l2_slow_tau``
        (hours).
        """
        cfg = self._config
        checkpoints = {"1d": 24.0, "7d": 168.0, "30d": 720.0}
        return {
            label: round(
                initial_strength * (
                    cfg.l2_fast_weight * math.exp(-hours / cfg.l2_fast_tau)
                    + (1.0 - cfg.l2_fast_weight) * math.exp(-hours / cfg.l2_slow_tau)
                ),
                4,
            )
            for label, hours in checkpoints.items()
        }

    def _next_consolidation_time(self) -> datetime:
        """Return the UTC datetime of the next scheduled consolidation."""
        return datetime.now(tz=timezone.utc) + timedelta(
            hours=self._config.consolidate_interval_hours
        )
