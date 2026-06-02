"""ASM-2 review scheduling — an agent memory adaptation of the SM-2 algorithm.

SM-2 (SuperMemo 2) is the classic spaced-repetition algorithm.  ASM-2 adapts
it for the HM-Arch memory system:

* A review is triggered when retention drops below a configurable threshold
  rather than on a fixed calendar schedule.
* Quality ratings (0–5) map onto the standard SM-2 ease-factor update formula.
* Helpers are pure functions so they can be called without a database.

Standard SM-2 definitions
--------------------------
* **Ease factor (EF)**: a per-memory multiplier controlling interval growth.
  Default 2.5, minimum 1.3.
* **Interval (I)**: days until the next scheduled review.
  * 1st successful review → I = 1 day
  * 2nd successful review → I = 6 days
  * nth successful review (n ≥ 3) → I = I_prev × EF
* **Quality (q)**: reviewer rating 0–5.
  * q < 3 → failure; interval resets to 1 day.
  * q ≥ 3 → success; interval advances per the schedule above.
* **EF update formula** (SM-2):
    EF' = EF + 0.1 − (5 − q) × (0.08 + (5 − q) × 0.02)
  The result is clamped to the minimum ease factor.

PRD numerical examples
----------------------
Starting EF = 2.5, applying :func:`update_ef`:

+-------+-------+
| q     | new EF|
+=======+=======+
| 5     | 2.60  |
| 4     | 2.50  |
| 3     | 2.36  |
| 2     | 2.18  |
| 1     | 1.96  |
| 0     | 1.70  |
+-------+-------+

Interval sequence for consecutive perfect reviews (q = 5, EF = 2.5 → 2.6 …):

* Review 1 → I = 1 day
* Review 2 → I = 6 days
* Review 3 → I = 6 × 2.6 = 15.6 days
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Optional


@dataclass
class ReviewResult:
    """Outcome returned by :func:`schedule_review`.

    Attributes
    ----------
    next_interval_days:
        Days until the next recommended review.
    new_ef:
        Updated ease factor after this review.
    next_review_at:
        Absolute datetime of the next review, or ``None`` if *base_time* was
        not supplied to :func:`schedule_review`.
    """

    next_interval_days: float
    new_ef: float
    next_review_at: Optional[datetime] = None


def update_ef(ef: float, quality: int, *, min_ef: float = 1.3) -> float:
    """Update ease factor after a review using the SM-2 formula.

    Parameters
    ----------
    ef:
        Current ease factor (must be ≥ *min_ef*).
    quality:
        Review quality rating, 0–5 (SM-2 convention).
        * 5 — perfect response
        * 4 — correct with slight hesitation
        * 3 — correct with significant difficulty
        * 2 — incorrect; correct answer seemed easy after seeing it
        * 1 — incorrect; correct answer felt difficult after seeing it
        * 0 — complete blackout
    min_ef:
        Minimum ease factor floor.

    Returns
    -------
    float
        New ease factor, clamped to *min_ef*.

    Raises
    ------
    ValueError
        If *quality* is outside 0–5.
    """
    if not 0 <= quality <= 5:
        raise ValueError(f"quality must be in 0–5, got {quality!r}")
    delta = 0.1 - (5 - quality) * (0.08 + (5 - quality) * 0.02)
    return max(min_ef, ef + delta)


def next_interval(
    review_count: int,
    last_interval_days: float,
    ef: float,
) -> float:
    """Compute the next review interval using SM-2 scheduling.

    Parameters
    ----------
    review_count:
        Total number of **successful** reviews completed so far, including
        the current one.  (1 = first success, 2 = second success, etc.)
    last_interval_days:
        Most recent interval in days.  Only used when *review_count* ≥ 3.
    ef:
        Current (already-updated) ease factor.

    Returns
    -------
    float
        Next interval in days.

    Raises
    ------
    ValueError
        If *review_count* is less than 1.
    """
    if review_count < 1:
        raise ValueError(f"review_count must be ≥ 1, got {review_count}")
    if review_count == 1:
        return 1.0
    if review_count == 2:
        return 6.0
    return last_interval_days * ef


def schedule_review(
    *,
    quality: int,
    review_count: int,
    ef: float,
    last_interval_days: float,
    min_ef: float = 1.3,
    base_time: Optional[datetime] = None,
) -> ReviewResult:
    """Compute an ASM-2 review schedule after a review attempt.

    Parameters
    ----------
    quality:
        Review quality 0–5.  Values < 3 are treated as failures and reset
        the interval to 1 day.
    review_count:
        Number of **successful** reviews completed *before* this attempt.
        A failure resets the count externally; the caller should pass 0 on
        the first post-failure review.
    ef:
        Current ease factor (the value *before* this review).
    last_interval_days:
        Most recent interval in days (used to compute the next interval when
        *review_count* ≥ 2 and *quality* ≥ 3).
    min_ef:
        Minimum ease factor floor (default 1.3, per SM-2 specification).
    base_time:
        If given, the absolute datetime of the review.  Used to populate
        ``next_review_at`` on the returned :class:`ReviewResult`.

    Returns
    -------
    ReviewResult
        Next interval, updated ease factor, and optional next-review datetime.
    """
    new_ef = update_ef(ef, quality, min_ef=min_ef)

    if quality < 3:
        # Failure: restart interval regardless of review history.
        interval = 1.0
    else:
        # Success: advance count and compute the next interval.
        new_count = review_count + 1
        interval = next_interval(new_count, last_interval_days, new_ef)

    next_review_at: Optional[datetime] = None
    if base_time is not None:
        next_review_at = base_time + timedelta(days=interval)

    return ReviewResult(
        next_interval_days=interval,
        new_ef=new_ef,
        next_review_at=next_review_at,
    )


def should_review(retention: float, *, trigger: float = 0.50) -> bool:
    """Return ``True`` when retention has dropped to or below *trigger*.

    Parameters
    ----------
    retention:
        Current retention value in [0, 1].
    trigger:
        Threshold below which a review is recommended.  Corresponds to
        :attr:`~hm_arch.config.MemoryConfig.review_trigger_retention`.
    """
    return retention <= trigger
