"""L6 Meta Memory — usage tracking and deterministic retrieval/consolidation policies.

L6 records how memories are accessed during search and stores simple key/value
policies in SQLite ``meta_memory`` that can tune retrieval and consolidation
without any online learning or external models.

Data sources
------------
* ``memory_index.access_count`` / ``last_accessed_at`` — canonical per-memory
  counters for rows that exist in the index (L2, L3, archived L4).
* ``meta_memory`` keys under ``hm_arch.l6.*`` — per (memory_id, layer) access
  tallies, per-layer totals, and named policy values.

Design notes
------------
* L6 does **not** inherit from :class:`~hm_arch.layers.base.BaseLayer`.
* Policies are deterministic strings; :meth:`strategy_plan` adds simple
  rule-based recommendations from observed access patterns.
* Thread-safety is not guaranteed; callers must synchronise if needed.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone

from ..storage.sqlite import SQLiteStore


__all__ = [
    "HotMemoryRecord",
    "StrategyPlan",
    "L6MetaMemory",
]

_LAYER: int = 6
_POLICY_PREFIX = "hm_arch.l6.policy."
_ACCESS_KEY_PREFIX = "hm_arch.l6.access."
_LAYER_TOTAL_PREFIX = "hm_arch.l6.layer_total"

_DEFAULT_POLICIES: dict[str, str] = {
    "retrieval_top_k_multiplier": "1.0",
    "consolidation_replay_ratio": "0.20",
    "hot_access_threshold": "3",
    "prefer_hot_memories": "false",
}


# ---------------------------------------------------------------------------
# Return types
# ---------------------------------------------------------------------------


@dataclass
class HotMemoryRecord:
    """A frequently accessed memory surfaced by :meth:`L6MetaMemory.get_hot_memories`.

    Attributes
    ----------
    memory_id:
        Identifier from ``memory_index``.
    layer:
        Layer index at access time (as stored in ``memory_index``).
    access_count:
        Total accesses recorded in ``memory_index.access_count``.
    last_accessed_at:
        Most recent access timestamp, if any.
    """

    memory_id: str
    layer: int
    access_count: int
    last_accessed_at: datetime | None


@dataclass
class StrategyPlan:
    """Current L6 policies plus deterministic tuning recommendations.

    Attributes
    ----------
    policies:
        Named policy values (string form, persisted in ``meta_memory``).
    recommendations:
        Human-readable suggestions derived from access statistics.
    hot_memory_count:
        Number of memories at or above ``hot_access_threshold``.
    layer_access_totals:
        Cumulative access events per layer from meta-memory counters.
    """

    policies: dict[str, str]
    recommendations: list[str] = field(default_factory=list)
    hot_memory_count: int = 0
    layer_access_totals: dict[int, int] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# L6 implementation
# ---------------------------------------------------------------------------


class L6MetaMemory:
    """Meta-cognitive memory layer (layer 6).

    Parameters
    ----------
    db:
        A connected :class:`~hm_arch.storage.sqlite.SQLiteStore` with schema
        initialised.  The caller owns the connection lifecycle.

    Examples
    --------
    ::

        from hm_arch.storage.sqlite import SQLiteStore
        from hm_arch.layers.l6_meta import L6MetaMemory

        db = SQLiteStore(":memory:").connect()
        db.initialize_schema()
        l6 = L6MetaMemory(db)
        l6.set_policy("consolidation_replay_ratio", "0.25")
        l6.track_access("abc123", layer=2)
        hot = l6.get_hot_memories(limit=5)
    """

    LAYER_INDEX: int = _LAYER

    def __init__(self, db: SQLiteStore) -> None:
        self._db = db

    # ------------------------------------------------------------------
    # Access tracking
    # ------------------------------------------------------------------

    def track_access(self, memory_id: str, layer: int) -> None:
        """Record one access for *memory_id* at *layer*.

        When a row exists in ``memory_index``, increments ``access_count`` and
        sets ``last_accessed_at``.  Always updates meta-memory counters for the
        (memory_id, layer) pair and the layer aggregate.

        Parameters
        ----------
        memory_id:
            Memory identifier (from search results or layer stores).
        layer:
            Layer index where the hit originated (1–4 in typical search flows).

        Raises
        ------
        ValueError
            If *memory_id* is empty or *layer* is negative.
        """
        if not memory_id:
            raise ValueError("memory_id must be non-empty")
        if layer < 0:
            raise ValueError(f"layer must be >= 0, got {layer!r}")

        now = _iso_now()

        rows = self._db.query(
            "SELECT id FROM memory_index WHERE id = ?",
            (memory_id,),
        )
        if rows:
            self._db.execute(
                """
                UPDATE memory_index
                SET    access_count     = access_count + 1,
                       last_accessed_at = ?,
                       updated_at       = ?
                WHERE  id = ?
                """,
                (now, now, memory_id),
            )

        access_key = f"{_ACCESS_KEY_PREFIX}{memory_id}.{layer}"
        current = self._load_meta_int(access_key)
        self._save_meta_value(access_key, str(current + 1))

        layer_key = f"{_LAYER_TOTAL_PREFIX}.{layer}"
        layer_total = self._load_meta_int(layer_key)
        self._save_meta_value(layer_key, str(layer_total + 1))

    def get_hot_memories(
        self,
        limit: int = 10,
        *,
        layer: int | None = None,
    ) -> list[HotMemoryRecord]:
        """Return the most accessed memories in descending access order.

        Parameters
        ----------
        limit:
            Maximum number of records to return.  Must be positive.
        layer:
            When set, restrict to ``memory_index`` rows with this layer value.

        Returns
        -------
        list[HotMemoryRecord]
            Rows ordered by ``access_count`` descending, then
            ``last_accessed_at`` descending (most recent first among ties).

        Raises
        ------
        ValueError
            If *limit* is less than 1.
        """
        if limit < 1:
            raise ValueError(f"limit must be >= 1, got {limit!r}")

        if layer is None:
            sql = """
                SELECT id, layer, access_count, last_accessed_at
                FROM   memory_index
                WHERE  access_count > 0
                ORDER  BY access_count DESC,
                         last_accessed_at DESC
                LIMIT  ?
            """
            params: tuple = (limit,)
        else:
            sql = """
                SELECT id, layer, access_count, last_accessed_at
                FROM   memory_index
                WHERE  access_count > 0 AND layer = ?
                ORDER  BY access_count DESC,
                         last_accessed_at DESC
                LIMIT  ?
            """
            params = (layer, limit)

        rows = self._db.query(sql, params)
        out: list[HotMemoryRecord] = []
        for row in rows:
            last_raw = row["last_accessed_at"]
            last_at = _parse_iso(last_raw) if last_raw else None
            out.append(
                HotMemoryRecord(
                    memory_id=row["id"],
                    layer=int(row["layer"]),
                    access_count=int(row["access_count"]),
                    last_accessed_at=last_at,
                )
            )
        return out

    # ------------------------------------------------------------------
    # Policies and strategy
    # ------------------------------------------------------------------

    def set_policy(self, name: str, value: str) -> None:
        """Persist a named policy value in ``meta_memory``.

        Parameters
        ----------
        name:
            Policy key without the ``hm_arch.l6.policy.`` prefix.
        value:
            String value stored verbatim.

        Raises
        ------
        ValueError
            If *name* is empty.
        """
        if not name:
            raise ValueError("policy name must be non-empty")
        key = f"{_POLICY_PREFIX}{name}"
        self._save_meta_value(key, value)

    def get_policy(self, name: str) -> str:
        """Return a policy value, falling back to built-in defaults."""
        key = f"{_POLICY_PREFIX}{name}"
        rows = self._db.query(
            "SELECT value FROM meta_memory WHERE key = ?",
            (key,),
        )
        if rows:
            return str(rows[0]["value"])
        return _DEFAULT_POLICIES.get(name, "")

    def strategy_plan(self) -> StrategyPlan:
        """Return current policies and simple deterministic recommendations.

        Recommendations are rule-based (no learning): they inspect hot-memory
        counts and per-layer access totals only.
        """
        policies = {name: self.get_policy(name) for name in _DEFAULT_POLICIES}
        layer_totals = self._layer_access_totals()
        hot_threshold = max(1, int(policies.get("hot_access_threshold", "3")))
        hot = self.get_hot_memories(limit=1000)
        hot_count = sum(1 for h in hot if h.access_count >= hot_threshold)

        recommendations: list[str] = []

        if hot_count > 0:
            recommendations.append(
                f"{hot_count} memor{'y' if hot_count == 1 else 'ies'} reached "
                f"hot access threshold ({hot_threshold}); consider enabling "
                "prefer_hot_memories or raising retrieval_top_k_multiplier."
            )
        else:
            recommendations.append(
                "No memories exceed the hot access threshold; default retrieval "
                "policies are appropriate."
            )

        l2_total = layer_totals.get(2, 0)
        l3_total = layer_totals.get(3, 0)
        if l2_total > 0 and l3_total == 0:
            recommendations.append(
                "Search traffic is episodic-heavy (L2 only); semantic consolidation "
                "may be under-exercised — consider running consolidate()."
            )
        elif l3_total > l2_total * 2 and l2_total > 0:
            recommendations.append(
                "Semantic (L3) accesses dominate episodic (L2); current "
                "consolidation_replay_ratio may be sufficient."
            )

        replay = policies.get("consolidation_replay_ratio", "0.20")
        try:
            replay_f = float(replay)
        except ValueError:
            replay_f = 0.20
        if replay_f < 0.10:
            recommendations.append(
                "consolidation_replay_ratio is below 0.10; increase if L2 "
                "memories should be replayed more aggressively during sleep."
            )
        elif replay_f > 0.40:
            recommendations.append(
                "consolidation_replay_ratio is above 0.40; lower it if "
                "consolidation cycles are too expensive."
            )

        return StrategyPlan(
            policies=policies,
            recommendations=recommendations,
            hot_memory_count=hot_count,
            layer_access_totals=layer_totals,
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _layer_access_totals(self) -> dict[int, int]:
        rows = self._db.query(
            "SELECT key, value FROM meta_memory WHERE key LIKE ?",
            (f"{_LAYER_TOTAL_PREFIX}.%",),
        )
        totals: dict[int, int] = {}
        prefix_len = len(_LAYER_TOTAL_PREFIX) + 1
        for row in rows:
            key = str(row["key"])
            try:
                layer = int(key[prefix_len:])
            except ValueError:
                continue
            totals[layer] = int(row["value"])
        return totals

    def _load_meta_int(self, key: str) -> int:
        rows = self._db.query(
            "SELECT value FROM meta_memory WHERE key = ?",
            (key,),
        )
        if not rows:
            return 0
        return int(rows[0]["value"])

    def _save_meta_value(self, key: str, value: str) -> None:
        now = _iso_now()
        self._db.execute(
            """
            INSERT INTO meta_memory (key, value, updated_at)
            VALUES (?, ?, ?)
            ON CONFLICT(key) DO UPDATE SET
                value      = excluded.value,
                updated_at = excluded.updated_at
            """,
            (key, value, now),
        )


# ---------------------------------------------------------------------------
# Module utilities
# ---------------------------------------------------------------------------


def _iso_now() -> str:
    return datetime.now(tz=timezone.utc).isoformat()


def _parse_iso(iso_str: str) -> datetime:
    dt = datetime.fromisoformat(iso_str)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt
