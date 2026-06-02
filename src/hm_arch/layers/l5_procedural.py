"""L5 Procedural Memory — durable skill / workflow store.

L5 stores procedural skills (templates, workflows, and reusable behaviors) in
the SQLite ``skills`` table.  Matching is **deterministic** and **offline**:
token-overlap scoring over ``name``, ``description``, and ``code`` (same
strategy as :class:`~hm_arch.storage.vector.LocalVectorStore`).

Design notes
------------
* L5 does not inherit from :class:`~hm_arch.layers.base.BaseLayer` — it uses
  the standalone ``skills`` table rather than ``memory_index``.
* :meth:`match_skill` increments ``usage_count`` and sets ``last_used_at``.
* :meth:`record_skill_result` updates ``success_rate`` and
  ``average_duration_ms`` from outcome history persisted in an optional
  machine-readable prefix on ``description`` (stripped from API-facing text).
* Thread-safety is not guaranteed; callers must synchronise if needed.
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone

from ..storage.sqlite import SQLiteStore
from ..storage.vector import _token_overlap_score, _tokenize


__all__ = [
    "ProceduralSkill",
    "L5ProceduralMemory",
]

_LAYER: int = 5

# Internal stats prefix embedded in description (stripped for callers).
_STATS_PREFIX_RE = re.compile(
    r"^<!--hm-l5-stats:successes=(\d+),attempts=(\d+),duration_sum=([\d.eE+-]+)-->\n?",
    re.MULTILINE,
)


# ---------------------------------------------------------------------------
# Return type
# ---------------------------------------------------------------------------


@dataclass
class ProceduralSkill:
    """A procedural skill stored in L5.

    Attributes
    ----------
    skill_id:
        Primary key in the ``skills`` table.
    name:
        Unique skill name (e.g. ``"git_push"``).
    description:
        Human-readable description (stats prefix stripped).
    code:
        Optional template or script body.
    usage_count:
        Number of times :meth:`~L5ProceduralMemory.match_skill` selected this
        skill.
    last_used_at:
        UTC timestamp of the most recent match, or ``None``.
    success_rate:
        Fraction of successful outcomes in ``[0, 1]``, or ``None`` before any
        :meth:`~L5ProceduralMemory.record_skill_result` call.
    average_duration_ms:
        Mean duration in milliseconds across recorded outcomes, or ``None``.
    relevance:
        Query relevance in ``[0, 1]`` (only set for :meth:`match_skill`
        results).
    """

    skill_id: str
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
        Connected :class:`~hm_arch.storage.sqlite.SQLiteStore` with schema
        initialised.  The caller owns the connection lifecycle.

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
            description="推代码到远程仓库",
            code="git push origin HEAD",
        )
        hit = l5.match_skill("推代码")
        assert hit is not None
        assert hit.name == "git_push"
    """

    LAYER_INDEX: int = _LAYER

    def __init__(self, db: SQLiteStore) -> None:
        self._db = db

    # ------------------------------------------------------------------
    # Primary public interface
    # ------------------------------------------------------------------

    def store_skill(
        self,
        name: str,
        *,
        description: str | None = None,
        code: str | None = None,
    ) -> str:
        """Persist a skill by unique *name*, returning its ``skill_id``.

        When a skill with the same *name* already exists, ``description`` and
        ``code`` are updated while usage and outcome statistics are preserved.

        Parameters
        ----------
        name:
            Unique skill identifier (e.g. ``"git_push"``).
        description:
            Optional natural-language description used for matching.
        code:
            Optional template or workflow body.

        Returns
        -------
        str
            The skill's primary key (``skills.id``).

        Raises
        ------
        ValueError
            When *name* is empty.
        """
        if not name or not name.strip():
            raise ValueError("name must be non-empty")
        name = name.strip()

        existing = self._fetch_by_name(name)
        stored_description = description
        if existing is not None:
            skill_id = existing["id"]
            # Preserve embedded stats prefix when updating description text.
            if description is not None:
                stored_description = _merge_user_description(
                    existing["description"], description
                )
            else:
                stored_description = existing["description"]
            self._db.execute(
                """
                UPDATE skills
                SET    description = ?,
                       code        = COALESCE(?, code)
                WHERE  name = ?
                """,
                (stored_description, code, name),
            )
            return skill_id

        skill_id = uuid.uuid4().hex
        self._db.execute(
            """
            INSERT INTO skills (id, name, description, code)
            VALUES (?, ?, ?, ?)
            """,
            (skill_id, name, stored_description, code),
        )
        return skill_id

    def match_skill(self, query: str) -> ProceduralSkill | None:
        """Return the most relevant skill for *query* and record reuse.

        Increments ``usage_count`` and sets ``last_used_at`` on the matched
        skill.  Returns ``None`` when no skills exist or every candidate scores
        zero relevance.

        Parameters
        ----------
        query:
            Natural-language or keyword query (CJK supported).

        Returns
        -------
        ProceduralSkill or None
        """
        if not query or not query.strip():
            return None

        rows = self._db.query("SELECT * FROM skills ORDER BY name ASC")
        if not rows:
            return None

        query_tokens = _tokenize(query)
        scored: list[tuple[float, dict]] = []
        for raw in rows:
            row = dict(raw)
            text = _skill_search_text(row)
            score = _token_overlap_score(query_tokens, _tokenize(text))
            scored.append((score, row))

        scored.sort(
            key=lambda item: (
                -item[0],
                item[1]["name"],
                item[1]["id"],
            )
        )
        best_score, best_row = scored[0]
        if best_score <= 0.0:
            return None

        now = _iso_now()
        self._db.execute(
            """
            UPDATE skills
            SET    usage_count  = usage_count + 1,
                   last_used_at = ?
            WHERE  id = ?
            """,
            (now, best_row["id"]),
        )
        best_row["usage_count"] = int(best_row["usage_count"]) + 1
        best_row["last_used_at"] = now

        return _row_to_skill(best_row, relevance=best_score)

    def list_skills(self) -> list[ProceduralSkill]:
        """Return every stored skill ordered by name."""
        rows = self._db.query("SELECT * FROM skills ORDER BY name ASC")
        return [_row_to_skill(dict(row)) for row in rows]

    def record_skill_result(
        self,
        name_or_id: str,
        *,
        success: bool,
        duration_ms: float,
    ) -> ProceduralSkill | None:
        """Record an execution outcome and update aggregate statistics.

        Updates ``success_rate`` (successes / attempts) and the running mean
        ``average_duration_ms``.  Does **not** increment ``usage_count``; only
        :meth:`match_skill` counts reuse.

        Parameters
        ----------
        name_or_id:
            Skill ``name`` or primary-key ``id``.
        success:
            Whether the execution succeeded.
        duration_ms:
            Wall-clock duration of the execution in milliseconds.  Must be
            non-negative.

        Returns
        -------
        ProceduralSkill or None
            Updated skill, or ``None`` when no matching skill exists.

        Raises
        ------
        ValueError
            When *duration_ms* is negative.
        """
        if duration_ms < 0:
            raise ValueError(f"duration_ms must be non-negative, got {duration_ms!r}")

        row = self._fetch_by_name_or_id(name_or_id)
        if row is None:
            return None

        successes, attempts, duration_sum = _parse_stats(row.get("description"))
        attempts += 1
        if success:
            successes += 1
        duration_sum += float(duration_ms)

        new_rate = successes / attempts
        new_avg = duration_sum / attempts
        new_description = _format_stats_description(
            row.get("description"), successes, attempts, duration_sum
        )

        self._db.execute(
            """
            UPDATE skills
            SET    description           = ?,
                   success_rate          = ?,
                   average_duration_ms   = ?
            WHERE  id = ?
            """,
            (new_description, new_rate, new_avg, row["id"]),
        )

        row["description"] = new_description
        row["success_rate"] = new_rate
        row["average_duration_ms"] = new_avg
        return _row_to_skill(row)

    def get_skill(self, name_or_id: str) -> ProceduralSkill | None:
        """Return a skill by *name* or *id* without matching side effects."""
        row = self._fetch_by_name_or_id(name_or_id)
        if row is None:
            return None
        return _row_to_skill(row)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _fetch_by_name(self, name: str) -> dict | None:
        rows = self._db.query("SELECT * FROM skills WHERE name = ?", (name,))
        if not rows:
            return None
        return dict(rows[0])

    def _fetch_by_name_or_id(self, name_or_id: str) -> dict | None:
        rows = self._db.query(
            "SELECT * FROM skills WHERE name = ? OR id = ?",
            (name_or_id, name_or_id),
        )
        if not rows:
            return None
        return dict(rows[0])


# ---------------------------------------------------------------------------
# Module-level utilities
# ---------------------------------------------------------------------------


def _skill_search_text(row: dict) -> str:
    """Concatenate searchable fields for token overlap."""
    parts = [row.get("name") or ""]
    desc = _visible_description(row.get("description"))
    if desc:
        parts.append(desc)
    if row.get("code"):
        parts.append(row["code"])
    return " ".join(parts)


def _visible_description(description: str | None) -> str | None:
    if description is None:
        return None
    stripped = _STATS_PREFIX_RE.sub("", description, count=1)
    return stripped or None


def _parse_stats(description: str | None) -> tuple[int, int, float]:
    """Return (successes, attempts, duration_sum) from embedded prefix."""
    if not description:
        return 0, 0, 0.0
    match = _STATS_PREFIX_RE.match(description)
    if not match:
        return 0, 0, 0.0
    successes = int(match.group(1))
    attempts = int(match.group(2))
    duration_sum = float(match.group(3))
    return successes, attempts, duration_sum


def _format_stats_description(
    description: str | None,
    successes: int,
    attempts: int,
    duration_sum: float,
) -> str | None:
    """Embed stats prefix while preserving user-visible description text."""
    visible = _visible_description(description)
    prefix = (
        f"<!--hm-l5-stats:successes={successes},attempts={attempts},"
        f"duration_sum={duration_sum:.6f}-->\n"
    )
    if visible:
        return prefix + visible
    if attempts > 0:
        return prefix.rstrip("\n")
    return visible


def _merge_user_description(
    existing: str | None,
    new_description: str,
) -> str:
    """Update visible description while keeping stats prefix."""
    successes, attempts, duration_sum = _parse_stats(existing)
    return _format_stats_description(new_description, successes, attempts, duration_sum)


def _row_to_skill(row: dict, *, relevance: float = 0.0) -> ProceduralSkill:
    last_used_raw = row.get("last_used_at")
    last_used = _parse_iso(last_used_raw) if last_used_raw else None
    success_rate = row.get("success_rate")
    avg_duration = row.get("average_duration_ms")
    return ProceduralSkill(
        skill_id=row["id"],
        name=row["name"],
        description=_visible_description(row.get("description")),
        code=row.get("code"),
        usage_count=int(row.get("usage_count") or 0),
        last_used_at=last_used,
        success_rate=float(success_rate) if success_rate is not None else None,
        average_duration_ms=(
            float(avg_duration) if avg_duration is not None else None
        ),
        relevance=relevance,
    )


def _iso_now() -> str:
    return datetime.now(tz=timezone.utc).isoformat()


def _parse_iso(iso_str: str) -> datetime:
    dt = datetime.fromisoformat(iso_str)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt
