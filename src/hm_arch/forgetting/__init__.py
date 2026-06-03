"""Forgetting sub-package: decay formulas and review scheduling.

Public re-exports so callers can do::

    from hm_arch.forgetting import l2_retention, schedule_review
"""

from .asm2 import (
    ReviewResult,
    next_interval,
    schedule_review,
    should_review,
    update_ef,
)
from .context_aware import (
    ContextAwareScore,
    MemoryForgettingInput,
    build_forgetting_input_from_row,
    compute_context_aware_score,
    passes_forgetting_threshold,
    privacy_forgetting_pressure,
    relevance_to_context,
)
from .controller import ForgettingController, LifecycleResult
from .decay import (
    l2_retention,
    l2_retention_from_config,
    l3_retention,
    l3_retention_from_config,
    predict_memory_retention_curve,
    predict_retention_curve,
)
from .strength import (
    CONSISTENCY_MOD_MAX,
    CONSISTENCY_MOD_MIN,
    EMOTION_MOD_MAX,
    EMOTION_MOD_MIN,
    IMPORTANCE_MOD_MAX,
    IMPORTANCE_MOD_MIN,
    PRD_STRENGTH_MAX,
    REPETITION_MOD_MAX,
    REPETITION_MOD_MIN,
    STRENGTH_BASE,
    StrengthFactors,
    apply_conflict_superseded_penalty,
    apply_consistent_strength_boost,
    apply_retrieval_reinforcement,
    apply_strength_to_retention,
    compute_initial_strength,
    compute_strength_from_factors,
    consistency_modifier_factor,
    content_hash,
    count_l2_repetitions,
    emotion_modifier_factor,
    importance_modifier_factor,
    load_strength_factors,
    merge_metadata_with_strength,
    repetition_modifier_factor,
    score_local_emotion,
    score_local_importance,
    strength_bounds,
)
from .time import ManualTimeProvider, SystemTimeProvider, TimeProvider

__all__ = [
    # decay
    "l2_retention",
    "l2_retention_from_config",
    "l3_retention",
    "l3_retention_from_config",
    "predict_memory_retention_curve",
    "predict_retention_curve",
    # asm2
    "ReviewResult",
    "update_ef",
    "next_interval",
    "schedule_review",
    "should_review",
    # lifecycle
    "ContextAwareScore",
    "MemoryForgettingInput",
    "build_forgetting_input_from_row",
    "compute_context_aware_score",
    "passes_forgetting_threshold",
    "privacy_forgetting_pressure",
    "relevance_to_context",
    "ForgettingController",
    "LifecycleResult",
    "TimeProvider",
    "SystemTimeProvider",
    "ManualTimeProvider",
    # strength modulation (HM-29)
    "STRENGTH_BASE",
    "IMPORTANCE_MOD_MIN",
    "IMPORTANCE_MOD_MAX",
    "EMOTION_MOD_MIN",
    "EMOTION_MOD_MAX",
    "REPETITION_MOD_MIN",
    "REPETITION_MOD_MAX",
    "CONSISTENCY_MOD_MIN",
    "CONSISTENCY_MOD_MAX",
    "PRD_STRENGTH_MAX",
    "StrengthFactors",
    "apply_conflict_superseded_penalty",
    "apply_consistent_strength_boost",
    "apply_retrieval_reinforcement",
    "apply_strength_to_retention",
    "compute_initial_strength",
    "compute_strength_from_factors",
    "consistency_modifier_factor",
    "content_hash",
    "count_l2_repetitions",
    "emotion_modifier_factor",
    "importance_modifier_factor",
    "load_strength_factors",
    "merge_metadata_with_strength",
    "repetition_modifier_factor",
    "score_local_emotion",
    "score_local_importance",
    "strength_bounds",
]
