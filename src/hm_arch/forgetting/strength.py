"""Deterministic memory strength modulation (HM-29).

PRD multiplicative model (offline by default)::

    S = S_base * I_mod * E_mod * R_mod * C_mod

* ``S_base = 0.5``
* ``I_mod`` in ``[1.0, 2.0]`` from importance ``[0, 1]``
* ``E_mod`` in ``[0.8, 1.5]`` from emotion ``[0, 1]``
* ``R_mod`` in ``[1.0, 3.0]`` from encode repetitions and successful retrievals
  (``+0.3`` per counted event, capped at ``3.0``)
* ``C_mod`` in ``[0.5, 1.5]`` (neutral ``1.0``, consistent ``1.5``,
  superseded conflict ``0.5``)

Retention scales as ``R(t) = min(1.0, R_layer(t) * S)`` so higher ``S`` decays
more slowly than the PRD default neutral memory.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

from ..types import EventType

if TYPE_CHECKING:
    from ..config import MemoryConfig
    from ..storage.sqlite import SQLiteStore
    from .time import TimeProvider

ConsistencyKind = Literal["neutral", "consistent", "conflict_superseded"]

STRENGTH_BASE = 0.5
IMPORTANCE_MOD_MIN = 1.0
IMPORTANCE_MOD_MAX = 2.0
EMOTION_MOD_MIN = 0.8
EMOTION_MOD_MAX = 1.5
REPETITION_MOD_MIN = 1.0
REPETITION_MOD_MAX = 3.0
CONSISTENCY_MOD_MIN = 0.5
CONSISTENCY_MOD_MAX = 1.5
PRD_STRENGTH_MAX = (
    STRENGTH_BASE
    * IMPORTANCE_MOD_MAX
    * EMOTION_MOD_MAX
    * REPETITION_MOD_MAX
    * CONSISTENCY_MOD_MAX
)

_DEFAULT_STRENGTH_MIN = 0.2
_DEFAULT_STRENGTH_MAX = PRD_STRENGTH_MAX
_DEFAULT_RETRIEVAL_INCREMENT = 0.3
_DEFAULT_RETRIEVAL_RELEVANCE_THRESHOLD = 0.25

_STRENGTH_META_KEY = "hm_arch_strength"

_EVENT_IMPORTANCE_BOOST: dict[EventType, float] = {
    EventType.ERROR: 0.20,
    EventType.DECISION: 0.15,
    EventType.TASK: 0.10,
    EventType.CODE: 0.05,
}

_EVENT_EMOTION_BOOST: dict[EventType, float] = {
    EventType.ERROR: 0.25,
    EventType.DECISION: 0.10,
}

_IMPORTANCE_KEYWORDS = frozenset(
    {
        "critical",
        "urgent",
        "important",
        "must",
        "never",
        "always",
        "essential",
        "priority",
    }
)

_EMOTION_LEXICON = frozenset(
    {
        "angry",
        "happy",
        "sad",
        "love",
        "hate",
        "fear",
        "worry",
        "excited",
        "frustrated",
        "delighted",
        "upset",
        "anxious",
        "thrilled",
        "terrible",
        "wonderful",
    }
)


@dataclass(frozen=True)
class StrengthFactors:
    """Inputs persisted for recomputing PRD strength after retrieval."""

    importance: float
    emotion: float
    encode_repetitions: int = 0
    successful_retrievals: int = 0
    consistency: ConsistencyKind = "neutral"


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def content_hash(content: str) -> str:
    """SHA-256 hex digest used for repetition detection."""
    return hashlib.sha256(content.encode()).hexdigest()


def score_local_importance(
    content: str,
    *,
    event_type: EventType = EventType.CONVERSATION,
    metadata: dict | None = None,
) -> float:
    """Heuristic importance in ``[0, 1]`` without an LLM."""
    score = 0.5
    score += _EVENT_IMPORTANCE_BOOST.get(event_type, 0.0)

    meta = metadata or {}
    for key in ("critical", "urgent", "high_priority", "priority"):
        if meta.get(key) in (True, "true", "1", 1):
            score += 0.15
            break

    score += min(0.10, len(content) / 400.0)

    lowered = content.lower()
    keyword_hits = sum(1 for word in _IMPORTANCE_KEYWORDS if word in lowered)
    score += min(0.15, 0.05 * keyword_hits)

    return _clamp(score, 0.0, 1.0)


def score_local_emotion(
    content: str,
    *,
    event_type: EventType = EventType.CONVERSATION,
) -> float:
    """Heuristic emotional salience in ``[0, 1]`` without an LLM."""
    score = 0.5
    score += _EVENT_EMOTION_BOOST.get(event_type, 0.0)

    exclamations = content.count("!") + content.count("?")
    score += min(0.10, 0.02 * exclamations)

    tokens = set(re.findall(r"[a-zA-Z]+", content.lower()))
    lexicon_hits = len(tokens & _EMOTION_LEXICON)
    score += min(0.20, 0.04 * lexicon_hits)

    return _clamp(score, 0.0, 1.0)


def importance_modifier_factor(importance: float) -> float:
    """Map importance in ``[0, 1]`` to ``I_mod`` in ``[1.0, 2.0]``."""
    imp = _clamp(importance, 0.0, 1.0)
    return IMPORTANCE_MOD_MIN + imp * (IMPORTANCE_MOD_MAX - IMPORTANCE_MOD_MIN)


def emotion_modifier_factor(emotion: float) -> float:
    """Map emotion in ``[0, 1]`` to ``E_mod`` in ``[0.8, 1.5]``."""
    emo = _clamp(emotion, 0.0, 1.0)
    return EMOTION_MOD_MIN + emo * (EMOTION_MOD_MAX - EMOTION_MOD_MIN)


def repetition_modifier_factor(
    *,
    encode_repetitions: int = 0,
    successful_retrievals: int = 0,
    increment: float = _DEFAULT_RETRIEVAL_INCREMENT,
) -> float:
    """Map repetition counts to ``R_mod`` in ``[1.0, 3.0]``."""
    if encode_repetitions < 0 or successful_retrievals < 0:
        raise ValueError("repetition counts must be non-negative")
    total = encode_repetitions + successful_retrievals
    return _clamp(
        REPETITION_MOD_MIN + increment * total,
        REPETITION_MOD_MIN,
        REPETITION_MOD_MAX,
    )


def consistency_modifier_factor(kind: ConsistencyKind) -> float:
    """Return ``C_mod`` for the given consistency state."""
    if kind == "consistent":
        return CONSISTENCY_MOD_MAX
    if kind == "conflict_superseded":
        return CONSISTENCY_MOD_MIN
    return 1.0


def compute_initial_strength(
    *,
    importance: float,
    emotion: float,
    encode_repetitions: int = 0,
    successful_retrievals: int = 0,
    consistency: ConsistencyKind = "neutral",
    strength_min: float = _DEFAULT_STRENGTH_MIN,
    strength_max: float = _DEFAULT_STRENGTH_MAX,
    retrieval_increment: float = _DEFAULT_RETRIEVAL_INCREMENT,
) -> float:
    """Combine PRD factors into clamped initial strength ``S``."""
    raw = (
        STRENGTH_BASE
        * importance_modifier_factor(importance)
        * emotion_modifier_factor(emotion)
        * repetition_modifier_factor(
            encode_repetitions=encode_repetitions,
            successful_retrievals=successful_retrievals,
            increment=retrieval_increment,
        )
        * consistency_modifier_factor(consistency)
    )
    return _clamp(raw, strength_min, strength_max)


def compute_strength_from_factors(
    factors: StrengthFactors,
    *,
    config: MemoryConfig | None = None,
) -> float:
    """Recompute ``S`` from :class:`StrengthFactors` and optional config."""
    s_min, s_max, increment, _ = strength_bounds(config) if config else (
        _DEFAULT_STRENGTH_MIN,
        _DEFAULT_STRENGTH_MAX,
        _DEFAULT_RETRIEVAL_INCREMENT,
        _DEFAULT_RETRIEVAL_RELEVANCE_THRESHOLD,
    )
    return compute_initial_strength(
        importance=factors.importance,
        emotion=factors.emotion,
        encode_repetitions=factors.encode_repetitions,
        successful_retrievals=factors.successful_retrievals,
        consistency=factors.consistency,
        strength_min=s_min,
        strength_max=s_max,
        retrieval_increment=increment,
    )


def encode_current_retention(initial_strength: float) -> float:
    """Retention probability stored at encode time.

    PRD ``initial_strength`` may exceed ``1.0`` as a decay multiplier; stored
    ``current_retention`` stays in ``[0, 1]`` for search and forgetting math.
    """
    return min(1.0, max(0.0, initial_strength))


def apply_strength_to_retention(
    layer_retention: float,
    initial_strength: float,
) -> float:
    """Scale a layer decay sample by PRD strength (cap at 1)."""
    return min(1.0, max(0.0, layer_retention) * max(0.0, initial_strength))


def strength_factors_to_metadata(factors: StrengthFactors) -> dict:
    """Serialize factors into ``memory_index.metadata``."""
    return {
        _STRENGTH_META_KEY: {
            "importance": factors.importance,
            "emotion": factors.emotion,
            "encode_repetitions": factors.encode_repetitions,
            "successful_retrievals": factors.successful_retrievals,
            "consistency": factors.consistency,
        }
    }


def load_strength_factors(
    metadata_json: str | None,
    *,
    fallback_importance: float,
    fallback_emotion: float,
) -> StrengthFactors:
    """Load persisted factors or build neutral defaults."""
    meta = decode_metadata(metadata_json)
    block = meta.get(_STRENGTH_META_KEY)
    if not isinstance(block, dict):
        return StrengthFactors(
            importance=fallback_importance,
            emotion=fallback_emotion,
        )
    consistency = block.get("consistency", "neutral")
    if consistency not in ("neutral", "consistent", "conflict_superseded"):
        consistency = "neutral"
    return StrengthFactors(
        importance=float(block.get("importance", fallback_importance)),
        emotion=float(block.get("emotion", fallback_emotion)),
        encode_repetitions=int(block.get("encode_repetitions", 0)),
        successful_retrievals=int(block.get("successful_retrievals", 0)),
        consistency=consistency,  # type: ignore[arg-type]
    )


def merge_metadata_with_strength(
    metadata: dict | None,
    factors: StrengthFactors,
) -> dict:
    """Return caller metadata merged with strength factor block."""
    base = dict(metadata) if metadata else {}
    base.update(strength_factors_to_metadata(factors))
    return base


def count_l2_repetitions(db: SQLiteStore, content: str) -> int:
    """Count active L2 rows with the same content hash before a new encode."""
    digest = content_hash(content)
    rows = db.query(
        """
        SELECT COUNT(*) AS cnt
        FROM   memory_index
        WHERE  layer = 2
          AND  status = 'active'
          AND  content_hash = ?
        """,
        (digest,),
    )
    return int(rows[0]["cnt"]) if rows else 0


def apply_retrieval_reinforcement(
    db: SQLiteStore,
    memory_id: str,
    relevance: float,
    *,
    config: MemoryConfig,
    time_provider: TimeProvider,
) -> bool:
    """Increment ``R_mod`` via successful retrieval (``+0.3``) and persist ``S``.

    Returns ``True`` when reinforcement was applied.
    """
    _, _, increment, threshold = strength_bounds(config)
    if relevance < threshold:
        return False

    rows = db.query(
        """
        SELECT mi.importance,
               mi.initial_strength,
               mi.current_retention,
               mi.metadata,
               e.emotion_score
        FROM   memory_index mi
        LEFT JOIN episodes e ON e.memory_id = mi.id
        WHERE  mi.id = ? AND mi.status = 'active'
        """,
        (memory_id,),
    )
    if not rows:
        return False

    row = rows[0]
    emotion = row["emotion_score"]
    if emotion is None:
        emotion = 0.5
    factors = load_strength_factors(
        row["metadata"],
        fallback_importance=float(row["importance"]),
        fallback_emotion=float(emotion),
    )
    factors = StrengthFactors(
        importance=factors.importance,
        emotion=factors.emotion,
        encode_repetitions=factors.encode_repetitions,
        successful_retrievals=factors.successful_retrievals + 1,
        consistency=factors.consistency,
    )
    new_strength = compute_strength_from_factors(factors, config=config)
    old_strength = float(row["initial_strength"])
    if new_strength <= old_strength:
        return False

    meta = decode_metadata(row["metadata"])
    meta.update(strength_factors_to_metadata(factors))
    retention = min(
        1.0,
        float(row["current_retention"])
        * (new_strength / old_strength if old_strength > 0 else 1.0),
    )
    _write_strength(
        db,
        memory_id,
        new_strength,
        retention,
        meta,
        config=config,
        time_provider=time_provider,
    )
    return True


def apply_consistent_strength_boost(
    db: SQLiteStore,
    memory_id: str,
    *,
    config: MemoryConfig | None = None,
    time_provider: TimeProvider | None = None,
) -> None:
    """Recompute strength with ``C_mod = 1.5`` for a consistent semantic fact."""
    _recompute_with_consistency(
        db,
        memory_id,
        consistency="consistent",
        config=config,
        time_provider=time_provider,
    )


def apply_conflict_superseded_penalty(
    db: SQLiteStore,
    memory_id: str,
    *,
    config: MemoryConfig | None = None,
    time_provider: TimeProvider | None = None,
) -> None:
    """Recompute strength with ``C_mod = 0.5`` for a superseded conflicting fact."""
    _recompute_with_consistency(
        db,
        memory_id,
        consistency="conflict_superseded",
        config=config,
        time_provider=time_provider,
    )


def _recompute_with_consistency(
    db: SQLiteStore,
    memory_id: str,
    *,
    consistency: ConsistencyKind,
    config: MemoryConfig | None,
    time_provider: TimeProvider | None,
) -> None:
    rows = db.query(
        """
        SELECT importance, current_retention, metadata
        FROM   memory_index
        WHERE  id = ?
        """,
        (memory_id,),
    )
    if not rows:
        return
    row = rows[0]
    factors = load_strength_factors(
        row["metadata"],
        fallback_importance=float(row["importance"]),
        fallback_emotion=0.5,
    )
    factors = StrengthFactors(
        importance=factors.importance,
        emotion=factors.emotion,
        encode_repetitions=factors.encode_repetitions,
        successful_retrievals=factors.successful_retrievals,
        consistency=consistency,
    )
    new_strength = compute_strength_from_factors(factors, config=config)
    meta = decode_metadata(row["metadata"])
    meta.update(strength_factors_to_metadata(factors))
    retention = apply_strength_to_retention(1.0, new_strength)
    retention = min(float(row["current_retention"]), retention)
    _write_strength(
        db,
        memory_id,
        new_strength,
        retention,
        meta,
        config=config,
        time_provider=time_provider,
    )


def _write_strength(
    db: SQLiteStore,
    memory_id: str,
    initial_strength: float,
    current_retention: float,
    metadata: dict,
    *,
    config: MemoryConfig | None = None,
    time_provider: TimeProvider | None = None,
) -> None:
    from .time import SystemTimeProvider

    s_min, s_max, _, _ = strength_bounds(config) if config else (
        _DEFAULT_STRENGTH_MIN,
        _DEFAULT_STRENGTH_MAX,
        _DEFAULT_RETRIEVAL_INCREMENT,
        _DEFAULT_RETRIEVAL_RELEVANCE_THRESHOLD,
    )
    strength = _clamp(initial_strength, s_min, s_max)
    retention = _clamp(current_retention, 0.0, 1.0)
    clock = time_provider or SystemTimeProvider()
    now = clock.now().isoformat()
    db.execute(
        """
        UPDATE memory_index
           SET initial_strength = ?,
               current_retention = ?,
               metadata = ?,
               updated_at = ?
         WHERE id = ?
        """,
        (strength, retention, json.dumps(metadata), now, memory_id),
    )


def strength_bounds(
    config: MemoryConfig | None,
) -> tuple[float, float, float, float]:
    """Return ``(min, max, retrieval_increment, relevance_threshold)``."""
    if config is None:
        return (
            _DEFAULT_STRENGTH_MIN,
            _DEFAULT_STRENGTH_MAX,
            _DEFAULT_RETRIEVAL_INCREMENT,
            _DEFAULT_RETRIEVAL_RELEVANCE_THRESHOLD,
        )
    return (
        config.strength_min,
        config.strength_max,
        config.retrieval_reinforcement_increment,
        config.retrieval_relevance_threshold,
    )


def decode_metadata(raw: str | None) -> dict:
    """Parse ``memory_index.metadata`` JSON safely."""
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}

