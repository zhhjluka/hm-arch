"""Automatic consolidation scheduling and conservative physical cleanup."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable

from ..config import MemoryConfig
from ..storage.sqlite import SQLiteStore
from ..types import ConsolidationReport, ForgetResult
from .context_aware import (
    ContextAwareScore,
    MemoryForgettingInput,
    build_forgetting_input_from_row,
    compute_context_aware_score,
    passes_forgetting_threshold,
)
from .time import SystemTimeProvider, TimeProvider


@dataclass
class LifecycleResult:
    """Outcome of a lifecycle tick (auto consolidate + physical cleanup)."""

    consolidation_report: ConsolidationReport | None = None
    cleanup_result: ForgetResult | None = None


class ForgettingController:
    """Operational automatic lifecycle for consolidation and cleanup.

    * When ``config.auto_consolidate`` is enabled, runs consolidation once
      every ``config.consolidate_interval_hours`` (measured by
      :class:`TimeProvider`, not wall-clock sleeps).
    * Performs conservative physical cleanup only for ``deletable`` rows whose
      ``deletable_at`` timestamp is older than
      ``config.deletion_safety_period_hours`` **and** whose PRD forgetting
      score meets ``config.forgetting_score_threshold``.
    * Populates retention, relevance, redundancy, contradiction, and privacy
      from stored data when evaluating lifecycle candidates.
    """

    _CANDIDATE_ROW_SQL = """
        SELECT mi.id,
               mi.layer,
               mi.status,
               mi.current_retention,
               mi.metadata,
               mi.updated_at,
               e.content AS episode_content,
               s.entity,
               s.relation,
               s.value,
               s.entity || ' ' || s.relation || ' ' || s.value AS semantic_content
        FROM   memory_index mi
        LEFT JOIN episodes e ON e.memory_id = mi.id
        LEFT JOIN semantics s ON s.memory_id = mi.id
    """

    def __init__(
        self,
        db: SQLiteStore,
        config: MemoryConfig,
        *,
        time_provider: TimeProvider | None = None,
        consolidate_fn: Callable[[], ConsolidationReport],
        forget_fn: Callable[[str], ForgetResult],
        context_query: str = "",
    ) -> None:
        self._db = db
        self._config = config
        self._time = time_provider or SystemTimeProvider()
        self._consolidate_fn = consolidate_fn
        self._forget_fn = forget_fn
        self._context_query = context_query
        self._lifecycle_started_at = self._time.now()

    @property
    def time_provider(self) -> TimeProvider:
        return self._time

    def set_context_query(self, query: str) -> None:
        """Update the query used for context-aware relevance scoring."""
        self._context_query = query

    def run_lifecycle_tick(self) -> LifecycleResult:
        """Run auto-consolidation (if due) and eligible physical cleanup."""
        report = self.maybe_auto_consolidate()
        cleanup = self.run_physical_cleanup()
        return LifecycleResult(
            consolidation_report=report,
            cleanup_result=cleanup if cleanup.forgotten_count else None,
        )

    def maybe_auto_consolidate(self) -> ConsolidationReport | None:
        """Run consolidation when auto mode is enabled and the interval elapsed."""
        if not self._config.auto_consolidate:
            return None

        last = self._last_consolidation_at()
        now = self._time.now()
        reference = last if last is not None else self._lifecycle_started_at
        elapsed_h = (now - reference).total_seconds() / 3600.0
        if elapsed_h < self._config.consolidate_interval_hours:
            return None

        return self._consolidate_fn()

    def score_row(self, row: dict, *, context_query: str | None = None) -> ContextAwareScore:
        """Compute the PRD forgetting score for a SQLite candidate row."""
        forgetting_input = build_forgetting_input_from_row(
            self._db,
            row,
            context_query=context_query or self._context_query,
            config=self._config,
        )
        return compute_context_aware_score(
            forgetting_input,
            context_query=context_query or self._context_query,
            config=self._config,
        )

    def is_forget_candidate(
        self,
        row: dict,
        *,
        context_query: str | None = None,
        require_safety_period: bool = False,
    ) -> bool:
        """Return whether *row* passes the PRD score gate (and optional safety wait)."""
        score = self.score_row(row, context_query=context_query)
        if not passes_forgetting_threshold(score, config=self._config):
            return False
        if not require_safety_period:
            return True
        if row.get("status") != "deletable":
            return True

        deletable_at = self._deletable_timestamp(dict(row))
        if deletable_at is None:
            return False
        elapsed_h = (self._time.now() - deletable_at).total_seconds() / 3600.0
        return elapsed_h >= float(self._config.deletion_safety_period_hours)

    def iter_scored_candidates(
        self,
        *,
        include_active: bool = False,
        context_query: str | None = None,
    ) -> list[tuple[dict, ContextAwareScore]]:
        """Return candidate rows with populated PRD forgetting scores."""
        rows = self._fetch_candidate_rows(include_active=include_active)
        query = context_query if context_query is not None else self._context_query
        scored: list[tuple[dict, ContextAwareScore]] = []
        for row in rows:
            record = dict(row)
            score = self.score_row(record, context_query=query)
            scored.append((record, score))
        return scored

    def run_physical_cleanup(self) -> ForgetResult:
        """Physically delete eligible deletable memories past the safety period.

        Memories are never removed before ``deletion_safety_period_hours`` have
        elapsed since ``deletable_at``.  Each candidate must also meet the PRD
        forgetting score threshold with populated context factors.
        """
        rows = self._db.query(
            self._CANDIDATE_ROW_SQL + " WHERE mi.status = 'deletable'"
        )

        forgotten = 0
        details: list[dict] = []
        affected_layers: set[int] = set()
        freed_bytes = 0

        for row in rows:
            record = dict(row)
            if not self.is_forget_candidate(
                record, require_safety_period=True
            ):
                continue

            result = self._forget_fn(record["id"])
            if result.forgotten_count or result.archived_count:
                forgotten += result.forgotten_count
                freed_bytes += int(result.freed_memory_mb * 1024 * 1024)
                affected_layers.update(result.affected_layers)
                details.extend(result.details)

        return ForgetResult(
            forgotten_count=forgotten,
            archived_count=0,
            freed_memory_mb=freed_bytes / (1024 * 1024),
            affected_layers=sorted(affected_layers),
            details=details,
        )

    def score_memory(
        self,
        memory: MemoryForgettingInput,
        *,
        context_query: str | None = None,
    ) -> ContextAwareScore:
        """Return the context-aware forgetting score for one memory."""
        return compute_context_aware_score(
            memory,
            context_query=context_query or self._context_query,
            config=self._config,
        )

    def _fetch_candidate_rows(self, *, include_active: bool) -> list[dict]:
        if include_active:
            cfg = self._config
            rows = self._db.query(
                self._CANDIDATE_ROW_SQL
                + """
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
        else:
            rows = self._db.query(
                self._CANDIDATE_ROW_SQL
                + " WHERE mi.status IN ('deletable', 'superseded')"
            )
        return [dict(row) for row in rows]

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
        return _parse_iso_timestamp(rows[0]["completed_at"])

    def _deletable_timestamp(self, row: dict) -> datetime | None:
        metadata = json.loads(row.get("metadata") or "{}")
        raw = metadata.get("deletable_at")
        if raw:
            return _parse_iso_timestamp(str(raw))
        updated = row.get("updated_at")
        if updated:
            return _parse_iso_timestamp(str(updated))
        return None


def _parse_iso_timestamp(iso_str: str) -> datetime:
    dt = datetime.fromisoformat(iso_str)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt
