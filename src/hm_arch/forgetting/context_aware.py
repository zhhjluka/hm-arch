"""Context-aware forgetting score from PRD retention and context factors."""

from __future__ import annotations

import json
from dataclasses import dataclass

from ..config import MemoryConfig
from ..layers.l3_semantic import _symmetric_text_similarity
from ..storage.sqlite import SQLiteStore
from ..storage.vector import _token_overlap_score, _tokenize

# PRD weights (must sum to 1.0)
_WEIGHT_RETENTION = 0.35
_WEIGHT_RELEVANCE = 0.25
_WEIGHT_REDUNDANCY = 0.15
_WEIGHT_CONTRADICTION = 0.15
_WEIGHT_PRIVACY = 0.10


@dataclass(frozen=True)
class ContextAwareScore:
    """Decomposed PRD forgetting score.

    Raw factors are in ``[0, 1]``.  :attr:`composite` is the weighted PRD sum::

        Forgetting_Score =
            0.35 * (1 - R)
          + 0.25 * (1 - Relevance)
          + 0.15 * Redundancy
          + 0.15 * Contradiction
          + 0.10 * Privacy

    Higher :attr:`composite` means the memory is more eligible for forgetting.
    """

    retention: float
    """Current retention ``R`` in ``[0, 1]``."""

    relevance: float
    """Context relevance in ``[0, 1]`` (higher = more relevant)."""

    redundancy: float
    """Redundancy pressure in ``[0, 1]``."""

    contradiction: float
    """Contradiction pressure in ``[0, 1]``."""

    privacy: float
    """Privacy-driven forgetting pressure in ``[0, 1]``."""

    composite: float
    """Weighted PRD forgetting score in ``[0, 1]``."""


@dataclass(frozen=True)
class MemoryForgettingInput:
    """Inputs required to score one memory for context-aware forgetting."""

    memory_id: str
    content: str
    retention: float
    layer: int
    status: str
    metadata: dict
    neighbor_similarity: float = 0.0
    has_active_conflict: bool = False


def relevance_to_context(query: str, content: str) -> float:
    """Return context relevance in ``[0, 1]`` for the PRD formula."""
    if not query.strip():
        return 0.5
    return _token_overlap_score(_tokenize(query), _tokenize(content))


def privacy_forgetting_pressure(metadata: dict) -> float:
    """Return the PRD ``Privacy`` term in ``[0, 1]``.

    Semantics
    ---------
    The privacy term models **pressure to remove sensitive data** during
    lifecycle cleanup (data-minimization), not protection from forgetting.

    * ``metadata["privacy_forget_pressure"]`` — explicit float in ``[0, 1]``.
    * ``metadata["private"] is True`` — treated as ``1.0``.
    * ``metadata["privacy"]`` in ``{"high", "strict", "pii"}`` — ``1.0``.
    * ``metadata["tags"]`` containing ``private`` / ``pii`` / ``secret`` /
      ``confidential`` — ``1.0``.
    * Otherwise — ``0.0``.
    """
    explicit = metadata.get("privacy_forget_pressure")
    if explicit is not None:
        try:
            return max(0.0, min(1.0, float(explicit)))
        except (TypeError, ValueError):
            pass

    if metadata.get("private") is True:
        return 1.0
    if metadata.get("privacy") in ("high", "strict", "pii"):
        return 1.0
    tags = metadata.get("tags")
    if isinstance(tags, (list, tuple, set)):
        lowered = {str(tag).lower() for tag in tags}
        if lowered & {"private", "pii", "secret", "confidential"}:
            return 1.0
    return 0.0


def redundancy_factor(
    neighbor_similarity: float, *, config: MemoryConfig
) -> float:
    """Map neighbour similarity to the PRD ``Redundancy`` term in ``[0, 1]``."""
    threshold = config.redundancy_threshold
    sim = max(0.0, min(1.0, float(neighbor_similarity)))
    if sim <= threshold:
        return 0.0
    return (sim - threshold) / max(1e-9, 1.0 - threshold)


def contradiction_factor(*, status: str, has_active_conflict: bool) -> float:
    """Return the PRD ``Contradiction`` term in ``[0, 1]``."""
    if status == "superseded" or has_active_conflict:
        return 1.0
    return 0.0


def compute_context_aware_score(
    memory: MemoryForgettingInput,
    *,
    context_query: str = "",
    config: MemoryConfig | None = None,
) -> ContextAwareScore:
    """Compute the PRD context-aware forgetting score for *memory*.

    Parameters
    ----------
    memory:
        Snapshot of the memory row and optional neighbour similarity.
    context_query:
        Current retrieval or session query used for relevance scoring.
    config:
        Optional config supplying ``redundancy_threshold``.

    Returns
    -------
    ContextAwareScore
        Raw PRD factors and the weighted composite score.
    """
    cfg = config or MemoryConfig()
    retention = max(0.0, min(1.0, float(memory.retention)))
    relevance = relevance_to_context(context_query, memory.content)
    redundancy = redundancy_factor(memory.neighbor_similarity, config=cfg)
    contradiction = contradiction_factor(
        status=memory.status,
        has_active_conflict=memory.has_active_conflict,
    )
    privacy = privacy_forgetting_pressure(memory.metadata)

    composite = (
        _WEIGHT_RETENTION * (1.0 - retention)
        + _WEIGHT_RELEVANCE * (1.0 - relevance)
        + _WEIGHT_REDUNDANCY * redundancy
        + _WEIGHT_CONTRADICTION * contradiction
        + _WEIGHT_PRIVACY * privacy
    )
    composite = max(0.0, min(1.0, composite))

    return ContextAwareScore(
        retention=retention,
        relevance=relevance,
        redundancy=redundancy,
        contradiction=contradiction,
        privacy=privacy,
        composite=composite,
    )


def passes_forgetting_threshold(
    score: ContextAwareScore, *, config: MemoryConfig
) -> bool:
    """Return whether *score* meets ``config.forgetting_score_threshold``."""
    return score.composite >= config.forgetting_score_threshold


def _memory_content_from_row(row: dict) -> str:
    episode = row.get("episode_content")
    if episode:
        return str(episode)
    semantic = row.get("semantic_content")
    if semantic:
        return str(semantic)
    entity = row.get("entity")
    relation = row.get("relation")
    value = row.get("value")
    if entity and relation and value:
        return f"{entity} {relation} {value}"
    return ""


def _has_semantic_conflict(db: SQLiteStore, memory_id: str) -> bool:
    rows = db.query(
        """
        SELECT s.entity, s.relation, s.value
        FROM   semantics s
        JOIN   memory_index mi ON mi.id = s.memory_id
        WHERE  s.memory_id = ?
          AND  mi.status = 'active'
        """,
        (memory_id,),
    )
    if not rows:
        return False

    entity = rows[0]["entity"]
    relation = rows[0]["relation"]
    value = rows[0]["value"]
    conflicts = db.query(
        """
        SELECT COUNT(*) AS n
        FROM   semantics s
        JOIN   memory_index mi ON mi.id = s.memory_id
        WHERE  s.entity = ?
          AND  s.relation = ?
          AND  s.value != ?
          AND  mi.status = 'active'
          AND  s.memory_id != ?
        """,
        (entity, relation, value, memory_id),
    )
    return bool(conflicts and int(conflicts[0]["n"]) > 0)


def _max_neighbor_similarity(
    db: SQLiteStore,
    *,
    memory_id: str,
    layer: int,
    content: str,
) -> float:
    if not content.strip():
        return 0.0

    if layer == 3:
        rows = db.query(
            """
            SELECT s.entity || ' ' || s.relation || ' ' || s.value AS content
            FROM   semantics s
            JOIN   memory_index mi ON mi.id = s.memory_id
            WHERE  mi.status IN ('active', 'deletable')
              AND  mi.id != ?
            """,
            (memory_id,),
        )
    else:
        rows = db.query(
            """
            SELECT e.content
            FROM   episodes e
            JOIN   memory_index mi ON mi.id = e.memory_id
            WHERE  mi.layer = ?
              AND  mi.status IN ('active', 'deletable')
              AND  mi.id != ?
            """,
            (layer, memory_id),
        )

    best = 0.0
    for row in rows:
        other = row["content"]
        if not other:
            continue
        best = max(best, _symmetric_text_similarity(content, str(other)))
    return best


def build_forgetting_input_from_row(
    db: SQLiteStore,
    row: dict,
    *,
    context_query: str,
    config: MemoryConfig,
) -> MemoryForgettingInput:
    """Build a populated :class:`MemoryForgettingInput` from SQLite data."""
    record = dict(row)
    content = _memory_content_from_row(record)
    metadata = json.loads(record.get("metadata") or "{}")
    memory_id = record["id"]
    layer = int(record["layer"])
    status = record["status"]
    has_conflict = status == "superseded" or _has_semantic_conflict(db, memory_id)
    neighbor_sim = _max_neighbor_similarity(
        db,
        memory_id=memory_id,
        layer=layer,
        content=content,
    )
    return MemoryForgettingInput(
        memory_id=memory_id,
        content=content,
        retention=float(record["current_retention"]),
        layer=layer,
        status=status,
        metadata=metadata,
        neighbor_similarity=neighbor_sim,
        has_active_conflict=has_conflict,
    )
