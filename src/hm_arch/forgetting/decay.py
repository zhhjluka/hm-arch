"""Forgetting curve mathematics for L2 and L3 memory layers.

L2 episodic memory uses **biexponential decay** — a fast component (short-term
consolidation window) and a slow component (long-term retention baseline):

    R_L2(t) = w_f · exp(−t / τ_f) + (1 − w_f) · exp(−t / τ_s)

L3 semantic memory uses **power-law decay**, consistent with the empirically
observed Ebbinghaus-like retention curve for factual knowledge:

    R_L3(t) = (1 + t / τ)^{−β}

Both functions accept time in hours (matching the ``MemoryConfig`` convention)
and return a retention value in [0, 1].
"""

from __future__ import annotations

import math
from typing import Optional

from hm_arch.config import MemoryConfig
from hm_arch.types import RetentionCurve

# Default day checkpoints used when none are supplied by the caller.
_DEFAULT_DAYS = [1, 3, 7, 14, 30, 60, 90]

# Upper bound used for binary-search of review / archive crossings (days).
_SEARCH_HORIZON_DAYS = 3650  # 10 years


def l2_retention(
    t_hours: float,
    *,
    fast_weight: float,
    fast_tau: float,
    slow_tau: float,
) -> float:
    """Compute L2 biexponential retention at time *t_hours* after encoding.

    Parameters
    ----------
    t_hours:
        Elapsed time since encoding, in hours.  Must be ≥ 0.
    fast_weight:
        Fraction of initial strength governed by the fast decay component
        (0–1).
    fast_tau:
        Fast-decay time constant in hours (τ_f).
    slow_tau:
        Slow-decay time constant in hours (τ_s).

    Returns
    -------
    float
        Retention value in [0, 1].

    Raises
    ------
    ValueError
        If *t_hours* is negative.
    """
    if t_hours < 0:
        raise ValueError(f"t_hours must be non-negative, got {t_hours}")
    slow_weight = 1.0 - fast_weight
    return (
        fast_weight * math.exp(-t_hours / fast_tau)
        + slow_weight * math.exp(-t_hours / slow_tau)
    )


def l3_retention(
    t_hours: float,
    *,
    tau: float,
    beta: float,
) -> float:
    """Compute L3 power-law retention at time *t_hours* after encoding.

    Parameters
    ----------
    t_hours:
        Elapsed time since encoding, in hours.  Must be ≥ 0.
    tau:
        Scale parameter in hours (τ).
    beta:
        Power-law exponent (β).  Larger values → faster forgetting.

    Returns
    -------
    float
        Retention value in [0, 1].

    Raises
    ------
    ValueError
        If *t_hours* is negative.
    """
    if t_hours < 0:
        raise ValueError(f"t_hours must be non-negative, got {t_hours}")
    return (1.0 + t_hours / tau) ** (-beta)


def l2_retention_from_config(t_hours: float, config: MemoryConfig) -> float:
    """Compute L2 retention using parameters from a :class:`MemoryConfig`.

    Convenience wrapper around :func:`l2_retention`.
    """
    return l2_retention(
        t_hours,
        fast_weight=config.l2_fast_weight,
        fast_tau=config.l2_fast_tau,
        slow_tau=config.l2_slow_tau,
    )


def l3_retention_from_config(t_hours: float, config: MemoryConfig) -> float:
    """Compute L3 retention using parameters from a :class:`MemoryConfig`.

    Convenience wrapper around :func:`l3_retention`.
    """
    return l3_retention(
        t_hours,
        tau=config.l3_tau,
        beta=config.l3_beta,
    )


def _find_crossing_day(
    decay_fn: "Callable[[float], float]",
    threshold: float,
    horizon: int = _SEARCH_HORIZON_DAYS,
) -> int:
    """Return the first integer day on which *decay_fn* drops to or below *threshold*.

    Uses binary search over whole-day granularity.  If the function never
    crosses *threshold* within *horizon* days, returns *horizon*.

    Parameters
    ----------
    decay_fn:
        A callable ``(t_hours: float) -> float`` giving retention.
    threshold:
        Retention level to detect (inclusive).
    horizon:
        Maximum day to search.
    """
    # If it never crosses within the horizon, return horizon.
    if decay_fn(horizon * 24.0) > threshold:
        return horizon

    lo, hi = 0, horizon
    while lo < hi:
        mid = (lo + hi) // 2
        if decay_fn(mid * 24.0) <= threshold:
            hi = mid
        else:
            lo = mid + 1
    return lo


def predict_memory_retention_curve(
    *,
    layer: int,
    initial_strength: float,
    config: MemoryConfig,
    days: Optional[list[int]] = None,
) -> RetentionCurve:
    """Build a retention curve scaled by a specific memory's initial strength.

    Samples use the layer's decay function multiplied by *initial_strength*
    (capped at 1.0), so memories encoded with lower strength follow a lower
    curve than the layer default.
    """
    if initial_strength < 0.0:
        raise ValueError(
            f"initial_strength must be non-negative, got {initial_strength!r}"
        )
    base = predict_retention_curve(layer=layer, config=config, days=days)
    scaled = [min(1.0, r * initial_strength) for r in base.retention]
    return RetentionCurve(
        days=base.days,
        retention=scaled,
        review_suggested_at_day=base.review_suggested_at_day,
        archive_at_day=base.archive_at_day,
    )


def predict_retention_curve(
    *,
    layer: int,
    config: MemoryConfig,
    days: Optional[list[int]] = None,
) -> RetentionCurve:
    """Build a :class:`~hm_arch.types.RetentionCurve` for the given layer.

    Parameters
    ----------
    layer:
        Memory layer index: 2 for L2 episodic, 3 for L3 semantic.
    config:
        :class:`MemoryConfig` instance providing decay parameters and
        thresholds.
    days:
        Sorted list of integer day offsets at which to sample retention.
        Defaults to ``[1, 3, 7, 14, 30, 60, 90]``.

    Returns
    -------
    RetentionCurve
        Retention samples plus the earliest day for review and archiving.

    Raises
    ------
    ValueError
        If *layer* is not 2 or 3.
    """
    if layer == 2:
        decay_fn = lambda t_h: l2_retention_from_config(t_h, config)  # noqa: E731
        archive_threshold = config.l2_archive_threshold
    elif layer == 3:
        decay_fn = lambda t_h: l3_retention_from_config(t_h, config)  # noqa: E731
        archive_threshold = config.l3_archive_threshold
    else:
        raise ValueError(
            f"predict_retention_curve supports layer 2 or 3, got {layer}"
        )

    if days is None:
        days = list(_DEFAULT_DAYS)

    retentions = [decay_fn(d * 24.0) for d in days]

    review_day = _find_crossing_day(decay_fn, config.review_trigger_retention)
    archive_day = _find_crossing_day(decay_fn, archive_threshold)

    return RetentionCurve(
        days=days,
        retention=retentions,
        review_suggested_at_day=review_day,
        archive_at_day=archive_day,
    )
