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
from .decay import (
    l2_retention,
    l2_retention_from_config,
    l3_retention,
    l3_retention_from_config,
    predict_memory_retention_curve,
    predict_retention_curve,
)

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
]
