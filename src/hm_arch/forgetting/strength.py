"""Deterministic memory strength modulation (HM-29).

All scoring is local, bounded, and offline by default.  Modifiers adjust
*initial_strength* at encode time; retention decay multiplies the layer curve
by that strength; successful retrieval reinforces strength for later decay.

Formulas
--------

**Initial strength** (clamped to ``[strength_min, strength_max]``)::

    S = clamp(
        1.0 + M_imp + M_emo + M_rep + M_con,
        strength_min,
        strength_max,
    )

Modifiers (each documented and bounded):

* ``M_imp = 0.20 * (importance - 0.5)``  → ``[-0.10, +0.10]``
* ``M_emo = 0.15 * (emotion - 0.5)``     → ``[-0.075, +0.075]``
* ``M_rep = min(0.12, 0.04 * repetition_count)``  → ``[0, +0.12]``
* ``M_con``: ``+0.08`` consistent reinforcement, ``0`` otherwise at encode
  (conflicting *superseded* rows receive a separate ``-0.12`` penalty)

**Retention** at elapsed hours *t*::

    R(t) = min(1.0, R_layer(t) * initial_strength)

where ``R_layer`` is the L2 bi-exponential or L3 power-law decay.

**Retrieval reinforcement** after a successful hit (relevance ≥ threshold)::

    ΔS = rate * relevance * (1 - initial_strength)
    S' = min(strength_max, initial_strength + ΔS)

    R' = min(1.0, R + rate * relevance * (1 - R))

**Semantic consistency adjustments** (applied directly to stored strength):

* Idempotent / merged consistent fact: ``+0.08`` to ``initial_strength`` and
  ``current_retention`` (capped at 1).
* Superseded conflicting fact: ``-0.12`` from both fields (floored at
  ``strength_min``).
"""

from __future__ import annotations

import hashlib
import json
import re
from typing import TYPE_CHECKING, Literal

from ..types import EventType

if TYPE_CHECKING:
    from ..config import MemoryConfig
    from ..storage.sqlite import SQLiteStore

ConsistencyKind = Literal["neutral", "consistent", "conflict_new", "conflict_superseded"]

# Modifier coefficients (documented bounds in module docstring).
_IMPORTANCE_SCALE = 0.20
_EMOTION_SCALE = 0.15
_REPETITION_STEP = 0.04
_REPETITION_CAP = 0.12
_CONSISTENT_BOOST = 0.08
_CONFLICT_SUPERSEDED_PENALTY = -0.12

_DEFAULT_STRENGTH_MIN = 0.25
_DEFAULT_STRENGTH_MAX = 1.0
_DEFAULT_REINFORCEMENT_RATE = 0.06
_DEFAULT_RETRIEVAL_RELEVANCE_THRESHOLD = 0.25

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


def importance_modifier(importance: float) -> float:
    """Bounded importance contribution to initial strength."""
    imp = _clamp(importance, 0.0, 1.0)
    return _IMPORTANCE_SCALE * (imp - 0.5)


def emotion_modifier(emotion: float) -> float:
    """Bounded emotion contribution to initial strength."""
    emo = _clamp(emotion, 0.0, 1.0)
    return _EMOTION_SCALE * (emo - 0.5)


def repetition_modifier(repetition_count: int) -> float:
    """Bounded boost from prior similar encodings (``repetition_count >= 0``)."""
    if repetition_count < 0:
        raise ValueError(f"repetition_count must be >= 0, got {repetition_count}")
    return min(_REPETITION_CAP, _REPETITION_STEP * repetition_count)


def consistency_modifier(kind: ConsistencyKind) -> float:
    """Bounded consistency / conflict adjustment at encode time."""
    if kind == "consistent":
        return _CONSISTENT_BOOST
    return 0.0


def compute_initial_strength(
    *,
    importance: float,
    emotion: float,
    repetition_count: int = 0,
    consistency: ConsistencyKind = "neutral",
    strength_min: float = _DEFAULT_STRENGTH_MIN,
    strength_max: float = _DEFAULT_STRENGTH_MAX,
) -> float:
    """Combine modifiers into a clamped initial strength."""
    raw = (
        1.0
        + importance_modifier(importance)
        + emotion_modifier(emotion)
        + repetition_modifier(repetition_count)
        + consistency_modifier(consistency)
    )
    return _clamp(raw, strength_min, strength_max)


def apply_strength_to_retention(
    layer_retention: float,
    initial_strength: float,
) -> float:
    """Scale a layer decay sample by *initial_strength* (cap at 1)."""
    return min(1.0, max(0.0, layer_retention) * _clamp(initial_strength, 0.0, 1.0))


def reinforcement_delta(
    *,
    initial_strength: float,
    current_retention: float,
    relevance: float,
    rate: float = _DEFAULT_REINFORCEMENT_RATE,
    strength_max: float = _DEFAULT_STRENGTH_MAX,
) -> tuple[float, float]:
    """Return updated ``(initial_strength, current_retention)`` after retrieval."""
    rel = _clamp(relevance, 0.0, 1.0)
    strength = _clamp(initial_strength, 0.0, strength_max)
    retention = _clamp(current_retention, 0.0, 1.0)

    delta_s = rate * rel * (1.0 - strength)
    new_strength = _clamp(strength + delta_s, 0.0, strength_max)

    delta_r = rate * rel * (1.0 - retention)
    new_retention = _clamp(retention + delta_r, 0.0, 1.0)

    return new_strength, new_retention


def count_l2_repetitions(db: SQLiteStore, content: str) -> int:
    """Count active L2 rows with the same content hash (excluding the new row)."""
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


def apply_consistent_strength_boost(
    db: SQLiteStore,
    memory_id: str,
    *,
    strength_min: float = _DEFAULT_STRENGTH_MIN,
    strength_max: float = _DEFAULT_STRENGTH_MAX,
) -> None:
    """Raise strength/retention for a reinforced consistent semantic fact."""
    rows = db.query(
        """
        SELECT initial_strength, current_retention
        FROM   memory_index
        WHERE  id = ?
        """,
        (memory_id,),
    )
    if not rows:
        return
    strength = float(rows[0]["initial_strength"]) + _CONSISTENT_BOOST
    retention = float(rows[0]["current_retention"]) + _CONSISTENT_BOOST
    _write_strength(db, memory_id, strength, retention, strength_min, strength_max)


def apply_conflict_superseded_penalty(
    db: SQLiteStore,
    memory_id: str,
    *,
    strength_min: float = _DEFAULT_STRENGTH_MIN,
) -> None:
    """Lower retention on facts superseded by a contradiction.

    ``initial_strength`` is left unchanged so transient supersession during
    replay does not permanently alter decay for a later-active canonical row.
    """
    rows = db.query(
        """
        SELECT initial_strength, current_retention
        FROM   memory_index
        WHERE  id = ?
        """,
        (memory_id,),
    )
    if not rows:
        return
    strength = float(rows[0]["initial_strength"])
    retention = float(rows[0]["current_retention"]) + _CONFLICT_SUPERSEDED_PENALTY
    _write_strength(db, memory_id, strength, retention, strength_min, 1.0)


def _write_strength(
    db: SQLiteStore,
    memory_id: str,
    initial_strength: float,
    current_retention: float,
    strength_min: float,
    strength_max: float,
) -> None:
    from .time import SystemTimeProvider

    strength = _clamp(initial_strength, strength_min, strength_max)
    retention = _clamp(current_retention, strength_min, strength_max)
    now = SystemTimeProvider().now().isoformat()
    db.execute(
        """
        UPDATE memory_index
           SET initial_strength = ?,
               current_retention = ?,
               updated_at = ?
         WHERE id = ?
        """,
        (strength, retention, now, memory_id),
    )


def strength_bounds(config: MemoryConfig) -> tuple[float, float, float, float]:
    """Return ``(min, max, reinforcement_rate, relevance_threshold)`` from config."""
    return (
        getattr(config, "strength_min", _DEFAULT_STRENGTH_MIN),
        getattr(config, "strength_max", _DEFAULT_STRENGTH_MAX),
        getattr(config, "retrieval_reinforcement_rate", _DEFAULT_REINFORCEMENT_RATE),
        getattr(
            config,
            "retrieval_relevance_threshold",
            _DEFAULT_RETRIEVAL_RELEVANCE_THRESHOLD,
        ),
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
