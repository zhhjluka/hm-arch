"""L5 Procedural Memory — durable skill / workflow store.

L5 stores named procedural skills (templates, workflows, code snippets) in the
SQLite ``skills`` table so agents can reuse successful behaviours offline.

Matching is **deterministic**: each skill is scored by token overlap between the
query and the concatenation of ``name``, ``description``, and ``code`` (same
strategy as :class:`~hm_arch.storage.vector.LocalVectorStore`).  No embeddings
or external LLM calls are required.

Usage and outcome statistics
----------------------------
* :meth:`match_skill` increments ``usage_count`` and sets ``last_used_at``.
* :meth:`record_skill_result` updates ``success_rate`` and ``average_duration_ms``
  using a simple cumulative mean.  The number of recorded outcomes per skill is
  tracked in ``meta_memory`` under keys ``hm_arch.l5.result_count.<skill_id>`` so
  averages remain correct after process restarts.

Design notes
------------
* L5 does **not** inherit from :class:`~hm_arch.layers.base.BaseLayer`.
* Skill ``name`` is unique; :meth:`store_skill` upserts by name.
* Thread-safety is not guaranteed; callers must synchronise if needed.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timezone

from ..storage.sqlite import SQLiteStore
from ..storage.vector import _token_overlap_score, _tokenize


__all__ = [
    "SkillRecord",
    "L5ProceduralMemory",
]

_LAYER: int = 5
_RESULT_COUNT_KEY_PREFIX = "hm_arch.l5.result_count."


# ---------------------------------------------------------------------------
# Return type
# ---------------------------------------------------------------------------


@dataclass
class SkillRecord:
    """A procedural skill stored in L5.

    Attributes
    ----------
    id:
        Primary key in the ``skills`` table.
    name:
        Unique skill identifier (e.g. ``"git_push"``).
    description:
        Human-readable description used for matching.
    code:
        Optional template or code snippet (not executed by HM-Arch).
    usage_count:
        Number of times :meth:`~L5ProceduralMemory.match_skill` selected this skill.
    last_used_at:
        UTC timestamp of the most recent match, if any.
    success_rate:
        Mean success rate in ``[0, 1]`` over :meth:`~L5ProceduralMemory.record_skill_result`
        calls, or ``None`` when no outcomes have been recorded.
    average_duration_ms:
        Mean duration in milliseconds over recorded outcomes, or ``None``.
    relevance:
        Query relevance in ``[0, 1]`` (meaningful for :meth:`~L5ProceduralMemory.match_skill`
        results; ``0.0`` otherwise).
    """

    id: str
    name: str
    description: str | None
    code: str | None
    usage_count: int
    last_used_at: datetime | None
    success_rate: float | None
    average_duration_ms: float | None
    relevance: float = 0.0


# ---------------------------------------------------------------------------
# L5 implementation
# ---------------------------------------------------------------------------


class L5ProceduralMemory:
    """Durable procedural memory layer (layer 5).

    Parameters
    ----------
    db:
        A connected :class:`~hm_arch.storage.sqlite.SQLiteStore` with schema
        initialised.  The caller owns the connection lifecycle.
    max_skills:
        Optional cap on the number of distinct skills.  When the cap is
        reached, :meth:`store_skill` raises ``ValueError`` for new names.
        ``None`` means no limit.

    Examples
    --------
    ::

        from hm_arch.storage.sqlite import SQLiteStore
        from hm_arch.layers.l5_procedural import L5ProceduralMemory

        db = SQLiteStore(":memory:").connect()
        db.initialize_schema()
        l5 = L5ProceduralMemory(db)
        l5.store_skill(
            "git_push",
            description="Push commits to remote 推代码",
            code="git push origin HEAD",
        )
        hit = l5.match_skill("推代码")
        assert hit is not None
        assert hit.name == "git_push"
    """

    LAYER_INDEX: int = _LAYER

    def __init__(
        self,
        db: SQLiteStore,
        max_skills: int | None = None,
    ) -> None:
        if max_skills is not None and max_skills < 1:
            raise ValueError(f"max_skills must be >= 1, got {max_skills!r}")
        self._db = db
        self._max_skills = max_skills

    # ------------------------------------------------------------------
    # Primary public interface
    # ------------------------------------------------------------------

    def store_skill(
        self,
        name: str,
        *,
        description: str | None = None,
        code: str | None = None,
        skill_id: str | None = None,
    ) -> SkillRecord:
        """Persist or update a skill by unique *name*.

        When a skill with the same *name* already exists, ``description`` and
        ``code`` are updated; usage and outcome statistics are preserved.

        Parameters
        ----------
        name:
            Unique skill name (e.g. ``"git_push"``).
        description:
            Optional text used for offline matching.
        code:
            Optional template or snippet (stored only; never executed).
        skill_id:
            Optional explicit primary key for new skills.  Ignored when
            upserting an existing name.

        Returns
        -------
        SkillRecord
            The stored skill row.

        Raises
        ------
        ValueError
            When *name* is empty or ``max_skills`` would be exceeded.
        """
        if not name or not name.strip():
            raise ValueError("name must be non-empty")

        existing = self._fetch_by_name(name)
        if existing is not None:
            self._db.execute(
                """
                UPDATE skills
                SET    description = ?,
                       code        = ?
                WHERE  name = ?
                """,
                (description, code, name),
            )
            return self._row_to_skill(self._fetch_by_name(name), relevance=0.0)

        if self._max_skills is not None and self.count() >= self._max_skills:
            raise ValueError(
                f"max_skills limit ({self._max_skills}) reached; cannot add {name!r}"
            )

        sid = skill_id or str(uuid.uuid4())
        self._db.execute(
            """
            INSERT INTO skills (id, name, description, code)
            VALUES (?, ?, ?, ?)
            """,
            (sid, name, description, code),
        )
        row = self._fetch_by_name(name)
        assert row is not None
        return self._row_to_skill(row, relevance=0.0)

    def match_skill(self, query: str, *, record_usage: bool = True) -> SkillRecord | None:
        """Return the skill most relevant to *query*.

        Scores every skill by token overlap on ``name``, ``description``, and
        ``code``.  Ties break on skill ``name`` ascending for stable ordering.

        When *record_usage* is ``True`` (default), the matched skill's
        ``usage_count`` is incremented and ``last_used_at`` is set to the
        current UTC time.

        Parameters
        ----------
        query:
            Free-text intent (may include CJK tokens).
        record_usage:
            When ``False``, ranking is performed without mutating statistics.

        Returns
        -------
        SkillRecord or None
            The best match, or ``None`` when the store is empty or no token
            overlap exists with any skill.
        """
        if not query or not query.strip():
            return None

        rows = self._db.query("SELECT * FROM skills ORDER BY name")
        if not rows:
            return None

        query_tokens = _tokenize(query)
        ranked: list[tuple[float, str, dict]] = []
        for row in rows:
            text = _skill_match_text(row["name"], row["description"], row["code"])
            score = _token_overlap_score(query_tokens, _tokenize(text))
            ranked.append((score, row["name"], row))

        ranked.sort(key=lambda item: (-item[0], item[1]))
        best_score, _, best_row = ranked[0]
        if best_score <= 0.0:
            return None
        best = self._row_to_skill(best_row, relevance=best_score)

        if record_usage:
            now = _iso_now()
            self._db.execute(
                """
                UPDATE skills
                SET    usage_count  = usage_count + 1,
                       last_used_at = ?
                WHERE  id = ?
                """,
                (now, best.id),
            )
            refreshed = self._fetch_by_id(best.id)
            assert refreshed is not None
            best = self._row_to_skill(refreshed, relevance=best_score)

        return best

    def list_skills(self) -> list[SkillRecord]:
        """Return all skills sorted by ``name`` (stable ordering)."""
        rows = self._db.query("SELECT * FROM skills ORDER BY name")
        return [self._row_to_skill(row, relevance=0.0) for row in rows]

    def record_skill_result(
        self,
        skill_id_or_name: str,
        success: bool,
        *,
        duration_ms: float | None = None,
    ) -> SkillRecord:
        """Record the outcome of applying a skill.

        Updates ``success_rate`` as the arithmetic mean of all recorded outcomes
        for this skill.  When *duration_ms* is provided, ``average_duration_ms``
        is updated with the arithmetic mean of supplied durations.

        Parameters
        ----------
        skill_id_or_name:
            Skill primary key or unique ``name``.
        success:
            ``True`` when the skill application succeeded.
        duration_ms:
            Optional elapsed time in milliseconds.

        Returns
        -------
        SkillRecord
            The skill row after the update.

        Raises
        ------
        ValueError
            When no skill matches *skill_id_or_name*, or *duration_ms* is
            negative.
        """
        if duration_ms is not None and duration_ms < 0:
            raise ValueError(f"duration_ms must be non-negative, got {duration_ms!r}")

        row = self._fetch_by_id(skill_id_or_name)
        if row is None:
            row = self._fetch_by_name(skill_id_or_name)
        if row is None:
            raise ValueError(f"skill not found: {skill_id_or_name!r}")

        skill_id = row["id"]
        n = self._load_result_count(skill_id)
        outcome = 1.0 if success else 0.0
        prior_rate = row["success_rate"]
        if prior_rate is None:
            new_rate = outcome
        else:
            new_rate = (float(prior_rate) * n + outcome) / (n + 1)

        new_avg = row["average_duration_ms"]
        if duration_ms is not None:
            if new_avg is None:
                new_avg = float(duration_ms)
            else:
                new_avg = (float(new_avg) * n + float(duration_ms)) / (n + 1)

        self._save_result_count(skill_id, n + 1)
        self._db.execute(
            """
            UPDATE skills
            SET    success_rate         = ?,
                   average_duration_ms  = ?
            WHERE  id = ?
            """,
            (new_rate, new_avg, skill_id),
        )

        refreshed = self._fetch_by_id(skill_id)
        assert refreshed is not None
        return self._row_to_skill(refreshed, relevance=0.0)

    def get_skill(self, skill_id_or_name: str) -> SkillRecord | None:
        """Return a skill by id or name without matching or mutating stats."""
        row = self._fetch_by_id(skill_id_or_name)
        if row is None:
            row = self._fetch_by_name(skill_id_or_name)
        if row is None:
            return None
        return self._row_to_skill(row, relevance=0.0)

    def count(self) -> int:
        """Return the number of skills in the store."""
        rows = self._db.query("SELECT COUNT(*) AS n FROM skills")
        return int(rows[0]["n"])

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _fetch_by_id(self, skill_id: str) -> dict | None:
        rows = self._db.query("SELECT * FROM skills WHERE id = ?", (skill_id,))
        return dict(rows[0]) if rows else None

    def _fetch_by_name(self, name: str) -> dict | None:
        rows = self._db.query("SELECT * FROM skills WHERE name = ?", (name,))
        return dict(rows[0]) if rows else None

    def _row_to_skill(self, row: dict, *, relevance: float) -> SkillRecord:
        if not isinstance(row, dict):
            row = dict(row)
        last_raw = row.get("last_used_at")
        last_used = _parse_iso(last_raw) if last_raw else None
        success = row.get("success_rate")
        avg_ms = row.get("average_duration_ms")
        return SkillRecord(
            id=row["id"],
            name=row["name"],
            description=row.get("description"),
            code=row.get("code"),
            usage_count=int(row.get("usage_count") or 0),
            last_used_at=last_used,
            success_rate=float(success) if success is not None else None,
            average_duration_ms=float(avg_ms) if avg_ms is not None else None,
            relevance=relevance,
        )

    def _result_count_key(self, skill_id: str) -> str:
        return f"{_RESULT_COUNT_KEY_PREFIX}{skill_id}"

    def _load_result_count(self, skill_id: str) -> int:
        rows = self._db.query(
            "SELECT value FROM meta_memory WHERE key = ?",
            (self._result_count_key(skill_id),),
        )
        if not rows:
            return 0
        return int(rows[0]["value"])

    def _save_result_count(self, skill_id: str, count: int) -> None:
        key = self._result_count_key(skill_id)
        now = _iso_now()
        self._db.execute(
            """
            INSERT INTO meta_memory (key, value, updated_at)
            VALUES (?, ?, ?)
            ON CONFLICT(key) DO UPDATE SET
                value      = excluded.value,
                updated_at = excluded.updated_at
            """,
            (key, str(count), now),
        )


# ---------------------------------------------------------------------------
# Module utilities
# ---------------------------------------------------------------------------


def _skill_match_text(
    name: str,
    description: str | None,
    code: str | None,
) -> str:
    """Canonical searchable text for a skill."""
    parts = [name]
    if description:
        parts.append(description)
    if code:
        parts.append(code)
    return " ".join(parts)


def _iso_now() -> str:
    return datetime.now(tz=timezone.utc).isoformat()


def _parse_iso(iso_str: str) -> datetime:
    dt = datetime.fromisoformat(iso_str)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt
