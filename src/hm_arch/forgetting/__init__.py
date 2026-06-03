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
]
