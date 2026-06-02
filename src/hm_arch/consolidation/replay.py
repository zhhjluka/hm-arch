"""Consolidation engine: replay L2 episodes, extract semantic triples, update retention.

This module is deliberately LLM-free.  All semantic extraction uses a
pattern-based fallback extractor so that consolidation passes offline tests
without any API keys.

Consolidation cycle steps
-------------------------
1. Apply layer-specific decay to ``current_retention`` for all active memories.
2. Randomly sample a fraction of active L2 episodes (controlled by
   ``config.replay_sample_ratio``).
3. Run each sampled episode through :class:`SemanticExtractor` and upsert any
   extracted triples into L3 semantic memory.
4. Schedule reviews in ``review_queue`` for important memories whose retention
   has fallen below ``config.review_trigger_retention``.
5. Mark memories below the delete threshold as ``'deletable'`` (no physical
   deletion — this is flagging only).
6. Write an audit row to ``consolidation_log`` and return a
   :class:`~hm_arch.types.ConsolidationReport`.
"""

from __future__ import annotations

import json
import math
import random
import re
import time
from datetime import datetime, timedelta, timezone

from ..config import MemoryConfig
from ..layers.l2_episodic import L2EpisodicBuffer
from ..layers.l3_semantic import L3SemanticMemory
from ..layers.l4_ltm import L4EpisodicLTM
from ..storage.sqlite import SQLiteStore
from ..types import ConsolidationReport


__all__ = [
    "SemanticExtractor",
    "ConsolidationEngine",
]


# ---------------------------------------------------------------------------
# Retention math (layer-specific decay formulas)
# ---------------------------------------------------------------------------


def _l2_retention(elapsed_hours: float, cfg: MemoryConfig) -> float:
    """Compute L2 bi-exponential retention given elapsed time in hours.

    Formula:
        R(t) = (1 - fast_weight) * exp(-t / slow_tau)
               + fast_weight     * exp(-t / fast_tau)
    """
    import math as _math

    slow = (1.0 - cfg.l2_fast_weight) * _math.exp(-elapsed_hours / cfg.l2_slow_tau)
    fast = cfg.l2_fast_weight * _math.exp(-elapsed_hours / cfg.l2_fast_tau)
    return slow + fast


def _l3_retention(elapsed_hours: float, cfg: MemoryConfig) -> float:
    """Compute L3 power-law retention given elapsed time in hours.

    Formula:
        R(t) = (1 + t / tau)^(-beta)
    """
    return (1.0 + elapsed_hours / cfg.l3_tau) ** (-cfg.l3_beta)


# ---------------------------------------------------------------------------
# Private ISO helpers
# ---------------------------------------------------------------------------


def _iso_now() -> str:
    """Return the current UTC time as an ISO 8601 string."""
    return datetime.now(tz=timezone.utc).isoformat()


def _parse_iso(iso_str: str) -> datetime:
    """Parse an ISO 8601 string into a timezone-aware :class:`datetime`.

    Strings without explicit timezone info are assumed to be UTC.
    """
    dt = datetime.fromisoformat(iso_str)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


# ---------------------------------------------------------------------------
# Fallback semantic extractor
# ---------------------------------------------------------------------------


class SemanticExtractor:
    """Pattern-based fallback semantic extractor (no LLM required).

    Extracts subject–relation–object triples from raw text using regular
    expressions.  Supports English preference / opinion sentences and a small
    set of common CJK verb patterns.

    Subject normalisation
    ~~~~~~~~~~~~~~~~~~~~~
    First-person and generic user references (``"I"``, ``"me"``, ``"user"``,
    ``"the user"``, ``"用户"`` …) are all normalised to ``"user"`` so that
    ``"I prefer Python"`` and ``"User prefers Python"`` produce the same
    entity key.

    Extraction priority
    ~~~~~~~~~~~~~~~~~~~
    1. English SVO (Subject–Verb–Object) with known preference verbs.
    2. CJK verb patterns (``偏好``, ``喜欢``, ``讨厌``, ``使用``, …).
    3. English ``"X is Y"`` copula pattern.
    4. English ``"X has Y"`` possession pattern.

    Only the first matching strategy produces output (to avoid duplicate
    triples from the same sentence).

    Examples
    --------
    ::

        extractor = SemanticExtractor()
        extractor.extract("User prefers Python")
        # [("user", "prefers", "Python")]

        extractor.extract("I like JavaScript")
        # [("user", "likes", "JavaScript")]

        extractor.extract("用户偏好 Python")
        # [("user", "prefers", "Python")]
    """

    # Canonical preference verbs: input variant → canonical form.
    PREFERENCE_VERBS: dict[str, str] = {
        "avoid": "avoids",
        "avoids": "avoids",
        "dislike": "dislikes",
        "dislikes": "dislikes",
        "enjoy": "enjoys",
        "enjoys": "enjoys",
        "favor": "favors",
        "favors": "favors",
        "hate": "hates",
        "hates": "hates",
        "know": "knows",
        "knows": "knows",
        "like": "likes",
        "likes": "likes",
        "love": "loves",
        "loves": "loves",
        "need": "needs",
        "needs": "needs",
        "prefer": "prefers",
        "prefers": "prefers",
        "use": "uses",
        "uses": "uses",
        "want": "wants",
        "wants": "wants",
    }

    # Subject aliases that normalise to "user".
    _USER_ALIASES: frozenset[str] = frozenset(
        {"user", "i", "the user", "me", "myself", "我", "用户"}
    )

    # Pre-compiled patterns — built once at class definition time.
    _SVO_PATTERN: re.Pattern = re.compile(
        r"^(.+?)\s+("
        + "|".join(sorted(PREFERENCE_VERBS.keys(), key=len, reverse=True))
        + r")\s+(.+?)\.?\s*$",
        re.IGNORECASE,
    )

    _IS_PATTERN: re.Pattern = re.compile(
        r"^(.+?)\s+is\s+(.+?)\.?\s*$",
        re.IGNORECASE,
    )

    _HAS_PATTERN: re.Pattern = re.compile(
        r"^(.+?)\s+has\s+(.+?)\.?\s*$",
        re.IGNORECASE,
    )

    # (compiled pattern, canonical relation) pairs for CJK verb matching.
    _CJK_PATTERNS: list[tuple[re.Pattern, str]] = [
        (re.compile(r"^(.+?)偏好\s*(.+?)$"), "prefers"),
        (re.compile(r"^(.+?)喜欢\s*(.+?)$"), "likes"),
        (re.compile(r"^(.+?)讨厌\s*(.+?)$"), "dislikes"),
        (re.compile(r"^(.+?)使用\s*(.+?)$"), "uses"),
        (re.compile(r"^(.+?)需要\s*(.+?)$"), "needs"),
        (re.compile(r"^(.+?)想要\s*(.+?)$"), "wants"),
        (re.compile(r"^(.+?)知道\s*(.+?)$"), "knows"),
    ]

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def extract(self, content: str) -> list[tuple[str, str, str]]:
        """Extract semantic triples from *content*.

        Parameters
        ----------
        content:
            Raw episode text to analyse.

        Returns
        -------
        list[tuple[str, str, str]]
            A (possibly empty) list of ``(entity, relation, value)`` triples.
            At most one triple is returned per call in the current
            implementation.
        """
        text = content.strip()
        if not text:
            return []

        triples = self._match_svo(text)
        if not triples:
            triples = self._match_cjk(text)
        if not triples:
            triples = self._match_is(text)
        if not triples:
            triples = self._match_has(text)
        return triples

    # ------------------------------------------------------------------
    # Internal pattern matchers
    # ------------------------------------------------------------------

    def _normalize_subject(self, raw: str) -> str:
        """Lowercase and normalise a subject string.

        Known user aliases (``"I"``, ``"the user"``, ``"用户"`` …) are mapped
        to the canonical key ``"user"``.
        """
        normalized = raw.lower().strip()
        return "user" if normalized in self._USER_ALIASES else normalized

    def _match_svo(self, text: str) -> list[tuple[str, str, str]]:
        """Match an English subject–preference-verb–object sentence."""
        m = self._SVO_PATTERN.match(text)
        if not m:
            return []
        subject = self._normalize_subject(m.group(1))
        verb_raw = m.group(2).lower()
        obj = m.group(3).strip().rstrip(".")
        relation = self.PREFERENCE_VERBS.get(verb_raw, verb_raw)
        if subject and relation and obj:
            return [(subject, relation, obj)]
        return []

    def _match_cjk(self, text: str) -> list[tuple[str, str, str]]:
        """Match a CJK verb pattern (e.g. ``"用户偏好 Python"``)."""
        for pattern, relation in self._CJK_PATTERNS:
            m = pattern.match(text)
            if m:
                subject = self._normalize_subject(m.group(1).strip())
                value = m.group(2).strip()
                if subject and value:
                    return [(subject, relation, value)]
        return []

    def _match_is(self, text: str) -> list[tuple[str, str, str]]:
        """Match an English ``"X is Y"`` copula sentence."""
        m = self._IS_PATTERN.match(text)
        if not m:
            return []
        subject = self._normalize_subject(m.group(1))
        value = m.group(2).strip().rstrip(".")
        if subject and value:
            return [(subject, "is", value)]
        return []

    def _match_has(self, text: str) -> list[tuple[str, str, str]]:
        """Match an English ``"X has Y"`` possession sentence."""
        m = self._HAS_PATTERN.match(text)
        if not m:
            return []
        subject = self._normalize_subject(m.group(1))
        value = m.group(2).strip().rstrip(".")
        if subject and value:
            return [(subject, "has", value)]
        return []


# ---------------------------------------------------------------------------
# Consolidation engine
# ---------------------------------------------------------------------------


class ConsolidationEngine:
    """Runs consolidation cycles against the memory store.

    A consolidation cycle:

    1. Applies layer-specific retention decay to all active L2 and L3
       memories in ``memory_index``.
    2. Randomly samples ``config.replay_sample_ratio`` of active L2 episodes.
    3. Extracts semantic triples from each sampled episode via the
       :class:`SemanticExtractor` and upserts them into L3.
    4. Schedules ASM-2 reviews for important memories whose retention has
       dropped below ``config.review_trigger_retention``.
    5. Archives eligible L2 episodes with retention below
       ``config.l2_archive_threshold`` into L4 and marks them ``'archived'`` in
       ``memory_index``.
    6. Marks memories below the layer-specific delete threshold as
       ``'deletable'`` (no physical deletion — flagging only).
    7. Writes an audit row to ``consolidation_log`` and returns a
       :class:`~hm_arch.types.ConsolidationReport`.

    Parameters
    ----------
    db:
        An already-connected :class:`~hm_arch.storage.sqlite.SQLiteStore`
        with the schema initialised.
    l2:
        An :class:`~hm_arch.layers.l2_episodic.L2EpisodicBuffer` backed by
        the same database.
    l3:
        An :class:`~hm_arch.layers.l3_semantic.L3SemanticMemory` backed by
        the same database.
    l4:
        Optional :class:`~hm_arch.layers.l4_ltm.L4EpisodicLTM` for compressing
        low-retention L2 episodes.  When ``None``, archival is skipped.
    config:
        Runtime configuration.  Defaults are used when ``None``.
    extractor:
        Optional custom extractor.  A :class:`SemanticExtractor` is created
        when ``None``.

    Examples
    --------
    ::

        from hm_arch.storage.sqlite import SQLiteStore
        from hm_arch.layers.l2_episodic import L2EpisodicBuffer
        from hm_arch.layers.l3_semantic import L3SemanticMemory
        from hm_arch.consolidation import ConsolidationEngine
        from hm_arch.config import MemoryConfig

        db = SQLiteStore(":memory:").connect()
        db.initialize_schema()
        l2 = L2EpisodicBuffer(db)
        l3 = L3SemanticMemory(db)
        config = MemoryConfig(replay_sample_ratio=1.0)
        engine = ConsolidationEngine(db, l2, l3, config=config)

        l2.encode("User prefers Python")
        report = engine.run_consolidation_cycle()
        assert report.extracted_semantics == 1
    """

    def __init__(
        self,
        db: SQLiteStore,
        l2: L2EpisodicBuffer,
        l3: L3SemanticMemory,
        l4: L4EpisodicLTM | None = None,
        config: MemoryConfig | None = None,
        extractor: SemanticExtractor | None = None,
    ) -> None:
        self._db = db
        self._l2 = l2
        self._l3 = l3
        self._l4 = l4
        self._config = config or MemoryConfig()
        self._extractor = extractor or SemanticExtractor()

    # ------------------------------------------------------------------
    # Primary public interface
    # ------------------------------------------------------------------

    def run_consolidation_cycle(self) -> ConsolidationReport:
        """Execute a full consolidation cycle and return a report.

        The cycle is atomic in the sense that each step reads committed SQLite
        state, but individual writes are committed as they happen (because
        :class:`~hm_arch.storage.sqlite.SQLiteStore` commits after every
        ``execute`` call).

        Returns
        -------
        ConsolidationReport
            Summary of what the cycle did.
        """
        t0 = time.monotonic()
        started_at = _iso_now()

        # Step 1: Apply decay to all active memories.
        self._update_retention_all()

        # Step 2: Sample L2 episodes for replay.
        episodes = self._sample_l2_episodes()

        # Step 3: Extract and upsert semantic triples.
        extracted = 0
        resolved_conflicts = 0
        for ep in episodes:
            triples = self._extractor.extract(ep["content"])
            for entity, relation, value in triples:
                existing = self._l3.get_by_entity_relation(entity, relation)
                self._l3.upsert(
                    entity,
                    relation,
                    value,
                    source_episodes=[ep["memory_id"]],
                    importance=ep["importance"],
                )
                if existing is not None and existing.value != value:
                    resolved_conflicts += 1
                extracted += 1

        # Step 4: Schedule reviews for important low-retention memories.
        scheduled = self._schedule_reviews()

        # Step 5: Archive low-retention L2 episodes to L4.
        archived = self._archive_eligible_l2()

        # Step 6: Flag memories below the delete threshold.
        deletable = self._mark_deletable()

        duration = time.monotonic() - t0
        completed_at = _iso_now()

        report = ConsolidationReport(
            extracted_semantics=extracted,
            merged_duplicates=0,
            resolved_conflicts=resolved_conflicts,
            archived_to_l4=archived,
            scheduled_reviews=scheduled,
            marked_deletable=deletable,
            duration_seconds=duration,
        )

        self._log_cycle(started_at, completed_at, duration, report)
        return report

    # ------------------------------------------------------------------
    # Internal cycle steps
    # ------------------------------------------------------------------

    def _update_retention_all(self) -> None:
        """Recompute ``current_retention`` for every active L2 and L3 memory.

        Formulas:

        * L2 bi-exponential:
          ``R = (1 - fast_weight) * exp(-t/slow_tau) + fast_weight * exp(-t/fast_tau)``
        * L3 power-law:
          ``R = (1 + t/tau)^(-beta)``

        Where ``t`` is elapsed time in hours since ``created_at``.  Only rows
        where the computed retention differs from the stored value (by more
        than 1e-9) are written back to avoid unnecessary I/O.
        """
        now = datetime.now(tz=timezone.utc)

        rows = self._db.query(
            """
            SELECT id, layer, created_at, current_retention
            FROM   memory_index
            WHERE  status = 'active'
              AND  layer  IN (2, 3)
            """
        )

        now_str = _iso_now()
        for row in rows:
            layer = row["layer"]
            created = _parse_iso(row["created_at"])
            elapsed_h = max(0.0, (now - created).total_seconds() / 3600.0)

            if layer == 2:
                new_ret = _l2_retention(elapsed_h, self._config)
            else:
                new_ret = _l3_retention(elapsed_h, self._config)

            new_ret = max(0.0, min(1.0, new_ret))
            if abs(new_ret - row["current_retention"]) > 1e-9:
                self._db.execute(
                    """
                    UPDATE memory_index
                       SET current_retention = ?,
                           updated_at        = ?
                     WHERE id = ?
                    """,
                    (new_ret, now_str, row["id"]),
                )

    def _sample_l2_episodes(self) -> list[dict]:
        """Return a random subset of active L2 episodes for replay.

        Sample size is ``ceil(replay_sample_ratio * total_active)``, capped
        at the total available count.  Returns an empty list when no active
        L2 episodes exist.
        """
        rows = self._db.query(
            """
            SELECT mi.id AS memory_id,
                   mi.importance,
                   mi.current_retention,
                   mi.created_at,
                   e.content
            FROM   memory_index mi
            JOIN   episodes     e ON e.memory_id = mi.id
            WHERE  mi.layer  = 2
              AND  mi.status = 'active'
            """
        )
        if not rows:
            return []

        all_eps = [
            {
                "memory_id": row["memory_id"],
                "importance": row["importance"],
                "current_retention": row["current_retention"],
                "created_at": row["created_at"],
                "content": row["content"],
            }
            for row in rows
        ]

        k = max(1, math.ceil(len(all_eps) * self._config.replay_sample_ratio))
        k = min(k, len(all_eps))
        return random.sample(all_eps, k)

    def _schedule_reviews(self) -> int:
        """Insert ``review_queue`` rows for important low-retention memories.

        Eligibility criteria:

        * ``status = 'active'``
        * ``layer IN (2, 3)``
        * ``current_retention < config.review_trigger_retention``
        * ``importance >= 0.5``
        * Memory is **not** already in ``review_queue``

        Urgency is computed as ``importance × (1 − retention)`` so that
        high-importance, low-retention memories float to the top of the queue.

        Returns the number of new rows inserted.
        """
        cfg = self._config
        next_review = (datetime.now(tz=timezone.utc) + timedelta(days=1)).isoformat()

        eligible_rows = self._db.query(
            """
            SELECT mi.id, mi.importance, mi.current_retention
            FROM   memory_index mi
            LEFT JOIN review_queue rq ON rq.memory_id = mi.id
            WHERE  mi.status = 'active'
              AND  mi.layer  IN (2, 3)
              AND  mi.current_retention < ?
              AND  mi.importance        >= 0.5
              AND  rq.memory_id IS NULL
            """,
            (cfg.review_trigger_retention,),
        )

        inserted = 0
        for row in eligible_rows:
            urgency = row["importance"] * (1.0 - row["current_retention"])
            cursor = self._db.execute(
                """
                INSERT OR IGNORE INTO review_queue
                    (memory_id, ef, current_interval, next_review_at, urgency)
                VALUES (?, ?, ?, ?, ?)
                """,
                (row["id"], cfg.initial_ef, 1, next_review, urgency),
            )
            inserted += cursor.rowcount

        return inserted

    def _mark_deletable(self) -> int:
        """Flag active memories below the delete threshold as ``'deletable'``.

        Thresholds:

        * L2: ``config.l2_delete_threshold`` (default 0.05)
        * L3: ``config.l3_delete_threshold`` (default 0.10)

        No rows are physically deleted — this is a status flag only.

        Returns the total number of rows updated.
        """
        cfg = self._config
        now_str = _iso_now()

        cur_l2 = self._db.execute(
            """
            UPDATE memory_index
               SET status     = 'deletable',
                   updated_at = ?
             WHERE layer   = 2
               AND status  = 'active'
               AND current_retention < ?
            """,
            (now_str, cfg.l2_delete_threshold),
        )

        cur_l3 = self._db.execute(
            """
            UPDATE memory_index
               SET status     = 'deletable',
                   updated_at = ?
             WHERE layer   = 3
               AND status  = 'active'
               AND current_retention < ?
            """,
            (now_str, cfg.l3_delete_threshold),
        )

        return cur_l2.rowcount + cur_l3.rowcount

    def _archive_eligible_l2(self) -> int:
        """Move active L2 episodes below the archive threshold into L4.

        Each archived row is written to the gzip store, marked ``'archived'``
        in ``memory_index``, and removed from the L2 vector index so only L4
        search surfaces it.  Episode rows remain in SQLite for audit.

        Returns the number of memories archived in this cycle.
        """
        if self._l4 is None:
            return 0

        cfg = self._config
        now_str = _iso_now()

        rows = self._db.query(
            """
            SELECT mi.id,
                   mi.created_at,
                   mi.updated_at,
                   mi.importance,
                   mi.current_retention,
                   mi.metadata,
                   e.content
            FROM   memory_index mi
            JOIN   episodes     e ON e.memory_id = mi.id
            WHERE  mi.layer  = 2
              AND  mi.status = 'active'
              AND  mi.current_retention < ?
            """,
            (cfg.l2_archive_threshold,),
        )

        archived = 0
        for row in rows:
            mid = row["id"]
            created = _parse_iso(row["created_at"])
            updated_raw = row["updated_at"]
            updated = _parse_iso(updated_raw) if updated_raw else None

            existing_meta = json.loads(row["metadata"] or "{}")
            archive_meta = dict(existing_meta)
            archive_meta["source_l2_memory_id"] = mid

            result = self._l4.archive(
                mid,
                row["content"],
                layer=2,
                created_at=created,
                updated_at=updated,
                retention=float(row["current_retention"]),
                importance=float(row["importance"]),
                metadata=archive_meta,
            )

            index_meta = dict(archive_meta)
            index_meta["l4_archive_path"] = result.path
            self._db.execute(
                """
                UPDATE memory_index
                   SET status     = 'archived',
                       updated_at = ?,
                       metadata   = ?
                 WHERE id = ?
                """,
                (now_str, json.dumps(index_meta), mid),
            )
            self._l2.evict_from_vector_index(mid)
            archived += 1

        return archived

    def _log_cycle(
        self,
        started_at: str,
        completed_at: str,
        duration_seconds: float,
        report: ConsolidationReport,
    ) -> None:
        """Write an audit row to ``consolidation_log``."""
        stats = {
            "extracted_semantics": report.extracted_semantics,
            "merged_duplicates": report.merged_duplicates,
            "resolved_conflicts": report.resolved_conflicts,
            "archived_to_l4": report.archived_to_l4,
            "scheduled_reviews": report.scheduled_reviews,
            "marked_deletable": report.marked_deletable,
        }
        self._db.execute(
            """
            INSERT INTO consolidation_log
                (started_at, completed_at, duration_seconds, stats)
            VALUES (?, ?, ?, ?)
            """,
            (started_at, completed_at, duration_seconds, json.dumps(stats)),
        )
