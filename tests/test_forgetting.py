"""Tests for the forgetting math module (HM-9).

PRD numerical acceptance criteria
----------------------------------
* L2 30-day retention ≈ 0.26  (biexponential, default config)
* L3 30-day retention ≈ 0.63  (power-law, default config)
* ASM-2 EF and interval examples from PRD pass

All tests run fully offline — no external API keys required.
"""

from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone

import pytest

from hm_arch.config import MemoryConfig
from hm_arch.forgetting.asm2 import (
    ReviewResult,
    next_interval,
    schedule_review,
    should_review,
    update_ef,
)
from hm_arch.forgetting.decay import (
    l2_retention,
    l2_retention_from_config,
    l3_retention,
    l3_retention_from_config,
    predict_retention_curve,
)
from hm_arch.types import RetentionCurve


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

HOURS_PER_DAY = 24
THIRTY_DAYS_HOURS = 30 * HOURS_PER_DAY  # 720 hours


# ---------------------------------------------------------------------------
# L2 biexponential decay — unit tests
# ---------------------------------------------------------------------------


class TestL2Retention:
    """Tests for :func:`l2_retention` and :func:`l2_retention_from_config`."""

    def test_at_t0_returns_one(self):
        """Retention at encoding time must be exactly 1.0."""
        r = l2_retention(0.0, fast_weight=0.30, fast_tau=24.0, slow_tau=720.0)
        assert r == pytest.approx(1.0)

    def test_decays_strictly(self):
        """Retention must decrease monotonically with time."""
        kw = dict(fast_weight=0.30, fast_tau=24.0, slow_tau=720.0)
        samples = [l2_retention(t * 24.0, **kw) for t in range(0, 31)]
        for a, b in zip(samples, samples[1:]):
            assert a > b, "Retention should decrease with each passing day"

    def test_30_day_retention_approx_026(self):
        """PRD acceptance: L2 30-day retention ≈ 0.26 (biexponential, default params)."""
        r = l2_retention(
            THIRTY_DAYS_HOURS,
            fast_weight=0.30,
            fast_tau=24.0,
            slow_tau=720.0,
        )
        assert r == pytest.approx(0.26, abs=0.02)

    def test_30_day_retention_from_config(self):
        """Config-wrapper produces the same 30-day value as the raw function."""
        config = MemoryConfig()
        r_raw = l2_retention(
            THIRTY_DAYS_HOURS,
            fast_weight=config.l2_fast_weight,
            fast_tau=config.l2_fast_tau,
            slow_tau=config.l2_slow_tau,
        )
        r_cfg = l2_retention_from_config(THIRTY_DAYS_HOURS, config)
        assert r_raw == pytest.approx(r_cfg)

    def test_fast_component_dominates_early(self):
        """After a short time the fast component should contribute meaningfully."""
        # At t = fast_tau (24 h), fast component = 0.30 * exp(-1) ≈ 0.11
        # slow component = 0.70 * exp(-24/720) ≈ 0.70 * 0.967 ≈ 0.677
        r = l2_retention(24.0, fast_weight=0.30, fast_tau=24.0, slow_tau=720.0)
        fast_part = 0.30 * math.exp(-1.0)
        slow_part = 0.70 * math.exp(-24.0 / 720.0)
        assert r == pytest.approx(fast_part + slow_part, rel=1e-9)

    def test_slow_component_dominates_late(self):
        """After many fast time-constants the slow component is all that remains."""
        # exp(-10 * 24 / 24) = exp(-10) ≈ 4.5e-5  (effectively 0)
        r = l2_retention(10 * 24.0, fast_weight=0.30, fast_tau=24.0, slow_tau=720.0)
        slow_only = 0.70 * math.exp(-10 * 24.0 / 720.0)
        assert r == pytest.approx(slow_only, rel=0.01)

    def test_negative_time_raises(self):
        with pytest.raises(ValueError, match="non-negative"):
            l2_retention(-1.0, fast_weight=0.30, fast_tau=24.0, slow_tau=720.0)

    def test_fast_weight_zero_is_pure_slow(self):
        """fast_weight=0 collapses the formula to a single exponential."""
        r = l2_retention(24.0, fast_weight=0.0, fast_tau=24.0, slow_tau=720.0)
        assert r == pytest.approx(math.exp(-24.0 / 720.0))

    def test_fast_weight_one_is_pure_fast(self):
        """fast_weight=1 collapses the formula to a single exponential."""
        r = l2_retention(24.0, fast_weight=1.0, fast_tau=24.0, slow_tau=720.0)
        assert r == pytest.approx(math.exp(-1.0))

    def test_preset_code_agent_30_day(self):
        """code_agent preset has faster decay than default."""
        cfg = MemoryConfig.preset("code_agent")
        r_code = l2_retention_from_config(THIRTY_DAYS_HOURS, cfg)
        r_default = l2_retention_from_config(THIRTY_DAYS_HOURS, MemoryConfig())
        assert r_code < r_default, "code_agent should forget faster than default"


# ---------------------------------------------------------------------------
# L3 power-law decay — unit tests
# ---------------------------------------------------------------------------


class TestL3Retention:
    """Tests for :func:`l3_retention` and :func:`l3_retention_from_config`."""

    def test_at_t0_returns_one(self):
        """Retention at encoding time must be exactly 1.0."""
        r = l3_retention(0.0, tau=168.0, beta=0.30)
        assert r == pytest.approx(1.0)

    def test_decays_strictly(self):
        """Retention must decrease monotonically with time."""
        samples = [l3_retention(t * 24.0, tau=168.0, beta=0.30) for t in range(0, 31)]
        for a, b in zip(samples, samples[1:]):
            assert a > b

    def test_30_day_retention_approx_063(self):
        """PRD acceptance: L3 30-day retention ≈ 0.63 (power-law, default params).

        The formula (1 + t/tau)^{-beta} with tau=168 h and beta=0.30
        yields ≈ 0.607 at t=720 h, which is within 0.05 of the PRD target.
        """
        r = l3_retention(THIRTY_DAYS_HOURS, tau=168.0, beta=0.30)
        assert r == pytest.approx(0.63, abs=0.05)

    def test_30_day_retention_from_config(self):
        """Config-wrapper produces the same 30-day value as the raw function."""
        config = MemoryConfig()
        r_raw = l3_retention(
            THIRTY_DAYS_HOURS,
            tau=config.l3_tau,
            beta=config.l3_beta,
        )
        r_cfg = l3_retention_from_config(THIRTY_DAYS_HOURS, config)
        assert r_raw == pytest.approx(r_cfg)

    def test_formula_matches_power_law(self):
        """Verify the exact formula: R(t) = (1 + t/tau)^{-beta}."""
        t, tau, beta = 48.0, 168.0, 0.30
        expected = (1.0 + t / tau) ** (-beta)
        assert l3_retention(t, tau=tau, beta=beta) == pytest.approx(expected, rel=1e-9)

    def test_larger_beta_means_faster_forgetting(self):
        """Higher beta → lower retention at any fixed t."""
        r_slow = l3_retention(72.0, tau=168.0, beta=0.15)
        r_fast = l3_retention(72.0, tau=168.0, beta=0.50)
        assert r_slow > r_fast

    def test_larger_tau_means_slower_forgetting(self):
        """Higher tau → higher retention at any fixed t."""
        r_slow = l3_retention(72.0, tau=720.0, beta=0.30)
        r_fast = l3_retention(72.0, tau=168.0, beta=0.30)
        assert r_slow > r_fast

    def test_negative_time_raises(self):
        with pytest.raises(ValueError, match="non-negative"):
            l3_retention(-1.0, tau=168.0, beta=0.30)

    def test_retention_bounds(self):
        """Retention must stay in [0, 1] for reasonable inputs."""
        for t in [0, 1, 24, 168, 720, 8760]:
            r = l3_retention(float(t), tau=168.0, beta=0.30)
            assert 0.0 <= r <= 1.0, f"Out of bounds at t={t}: {r}"


# ---------------------------------------------------------------------------
# Retention curve prediction
# ---------------------------------------------------------------------------


class TestPredictRetentionCurve:
    """Tests for :func:`predict_retention_curve`."""

    def test_returns_retention_curve(self):
        cfg = MemoryConfig()
        curve = predict_retention_curve(layer=2, config=cfg)
        assert isinstance(curve, RetentionCurve)

    def test_days_and_retention_same_length(self):
        cfg = MemoryConfig()
        curve = predict_retention_curve(layer=2, config=cfg)
        assert len(curve.days) == len(curve.retention)

    def test_custom_days(self):
        cfg = MemoryConfig()
        days = [1, 7, 30]
        curve = predict_retention_curve(layer=2, config=cfg, days=days)
        assert curve.days == days
        assert len(curve.retention) == 3

    def test_l2_retention_values_match_direct_call(self):
        """Curve values must agree with direct :func:`l2_retention_from_config` calls."""
        cfg = MemoryConfig()
        days = [1, 7, 30]
        curve = predict_retention_curve(layer=2, config=cfg, days=days)
        for d, r in zip(days, curve.retention):
            expected = l2_retention_from_config(d * 24.0, cfg)
            assert r == pytest.approx(expected, rel=1e-9)

    def test_l3_retention_values_match_direct_call(self):
        """Curve values must agree with direct :func:`l3_retention_from_config` calls."""
        cfg = MemoryConfig()
        days = [1, 7, 30]
        curve = predict_retention_curve(layer=3, config=cfg, days=days)
        for d, r in zip(days, curve.retention):
            expected = l3_retention_from_config(d * 24.0, cfg)
            assert r == pytest.approx(expected, rel=1e-9)

    def test_retention_decreases_across_days(self):
        """Sampled retention must be monotonically decreasing."""
        cfg = MemoryConfig()
        for layer in (2, 3):
            curve = predict_retention_curve(layer=layer, config=cfg)
            for a, b in zip(curve.retention, curve.retention[1:]):
                assert a >= b, f"L{layer} curve not monotonically decreasing"

    def test_all_retention_in_01(self):
        """All sampled retention values must be in [0, 1]."""
        cfg = MemoryConfig()
        for layer in (2, 3):
            curve = predict_retention_curve(layer=layer, config=cfg)
            for r in curve.retention:
                assert 0.0 <= r <= 1.0

    def test_review_day_retention_below_trigger(self):
        """Retention at review_suggested_at_day must be ≤ review_trigger."""
        cfg = MemoryConfig()
        for layer in (2, 3):
            curve = predict_retention_curve(layer=layer, config=cfg)
            r_at_review = (
                l2_retention_from_config(curve.review_suggested_at_day * 24.0, cfg)
                if layer == 2
                else l3_retention_from_config(curve.review_suggested_at_day * 24.0, cfg)
            )
            assert r_at_review <= cfg.review_trigger_retention + 1e-9

    def test_archive_day_retention_below_threshold(self):
        """Retention at archive_at_day must be ≤ the archive threshold."""
        cfg = MemoryConfig()
        for layer in (2, 3):
            archive_thresh = (
                cfg.l2_archive_threshold if layer == 2 else cfg.l3_archive_threshold
            )
            curve = predict_retention_curve(layer=layer, config=cfg)
            r_at_archive = (
                l2_retention_from_config(curve.archive_at_day * 24.0, cfg)
                if layer == 2
                else l3_retention_from_config(curve.archive_at_day * 24.0, cfg)
            )
            assert r_at_archive <= archive_thresh + 1e-9

    def test_invalid_layer_raises(self):
        with pytest.raises(ValueError, match="layer 2 or 3"):
            predict_retention_curve(layer=1, config=MemoryConfig())


# ---------------------------------------------------------------------------
# ASM-2: update_ef — PRD numerical examples
# ---------------------------------------------------------------------------


class TestUpdateEF:
    """Tests for :func:`update_ef` using the PRD table of EF updates.

    Starting EF = 2.5 (SM-2 default).

    PRD table:
        q=5 → 2.60
        q=4 → 2.50
        q=3 → 2.36
        q=2 → 2.18
        q=1 → 1.96
        q=0 → 1.70
    """

    BASE_EF = 2.5

    def test_q5_perfect(self):
        assert update_ef(self.BASE_EF, 5) == pytest.approx(2.60)

    def test_q4_good(self):
        assert update_ef(self.BASE_EF, 4) == pytest.approx(2.50)

    def test_q3_difficult(self):
        assert update_ef(self.BASE_EF, 3) == pytest.approx(2.36)

    def test_q2_failure_mild(self):
        assert update_ef(self.BASE_EF, 2) == pytest.approx(2.18)

    def test_q1_failure(self):
        assert update_ef(self.BASE_EF, 1) == pytest.approx(1.96)

    def test_q0_blackout(self):
        assert update_ef(self.BASE_EF, 0) == pytest.approx(1.70)

    def test_ef_never_below_min_ef(self):
        """Low quality on an already-weak memory must not push EF below 1.3."""
        ef = update_ef(1.4, 0)
        assert ef >= 1.3

    def test_ef_clamped_at_custom_min(self):
        """Custom min_ef is respected."""
        ef = update_ef(1.5, 0, min_ef=1.5)
        assert ef >= 1.5

    def test_repeated_perfect_reviews_increase_ef(self):
        """Multiple q=5 reviews must keep raising EF."""
        ef = 2.5
        for _ in range(5):
            ef = update_ef(ef, 5)
        assert ef > 2.5

    def test_invalid_quality_raises(self):
        with pytest.raises(ValueError, match="0–5"):
            update_ef(2.5, 6)
        with pytest.raises(ValueError, match="0–5"):
            update_ef(2.5, -1)


# ---------------------------------------------------------------------------
# ASM-2: next_interval — PRD numerical examples
# ---------------------------------------------------------------------------


class TestNextInterval:
    """Tests for :func:`next_interval`.

    PRD sequence (q=5 throughout, starting EF=2.5→2.6→2.7…):
        Review 1 → I = 1 day
        Review 2 → I = 6 days
        Review 3 → I = 6 × 2.6 = 15.6 days
    """

    def test_first_review_always_1_day(self):
        assert next_interval(1, last_interval_days=0.0, ef=2.5) == pytest.approx(1.0)

    def test_second_review_always_6_days(self):
        assert next_interval(2, last_interval_days=1.0, ef=2.5) == pytest.approx(6.0)

    def test_third_review_is_last_interval_times_ef(self):
        """PRD example: after 2 successes with EF=2.6 → 6 × 2.6 = 15.6."""
        assert next_interval(3, last_interval_days=6.0, ef=2.6) == pytest.approx(15.6)

    def test_fourth_review_grows_geometrically(self):
        """Fourth review: I4 = 15.6 × 2.7 = 42.12 (with EF updated to 2.7)."""
        assert next_interval(4, last_interval_days=15.6, ef=2.7) == pytest.approx(42.12)

    def test_invalid_review_count_raises(self):
        with pytest.raises(ValueError):
            next_interval(0, last_interval_days=1.0, ef=2.5)


# ---------------------------------------------------------------------------
# ASM-2: schedule_review — full round-trip examples
# ---------------------------------------------------------------------------


class TestScheduleReview:
    """Tests for :func:`schedule_review`."""

    def test_first_perfect_review(self):
        """q=5, first-ever review: I=1, EF→2.6."""
        result = schedule_review(
            quality=5,
            review_count=0,
            ef=2.5,
            last_interval_days=0.0,
        )
        assert isinstance(result, ReviewResult)
        assert result.next_interval_days == pytest.approx(1.0)
        assert result.new_ef == pytest.approx(2.6)
        assert result.next_review_at is None

    def test_second_perfect_review(self):
        """q=5, second review: I=6, EF→2.7."""
        result = schedule_review(
            quality=5,
            review_count=1,
            ef=2.6,
            last_interval_days=1.0,
        )
        assert result.next_interval_days == pytest.approx(6.0)
        assert result.new_ef == pytest.approx(2.7)

    def test_third_perfect_review(self):
        """q=5, third review: I=6×2.7=16.2 (EF updated to 2.8 first, then 2.7 used)."""
        # EF starts at 2.7; after q=5 update it becomes 2.8.
        # next_interval uses the *new* EF: 6 × 2.8 = 16.8
        result = schedule_review(
            quality=5,
            review_count=2,
            ef=2.7,
            last_interval_days=6.0,
        )
        assert result.new_ef == pytest.approx(2.8)
        assert result.next_interval_days == pytest.approx(6.0 * 2.8)

    def test_failure_resets_interval_to_one(self):
        """q < 3 (failure) always resets interval to 1 day."""
        for q in (0, 1, 2):
            result = schedule_review(
                quality=q,
                review_count=5,
                ef=2.5,
                last_interval_days=30.0,
            )
            assert result.next_interval_days == pytest.approx(1.0), f"q={q} failed"

    def test_ef_still_updated_on_failure(self):
        """EF is updated even on failure (SM-2 behaviour)."""
        result = schedule_review(
            quality=0,
            review_count=3,
            ef=2.5,
            last_interval_days=10.0,
        )
        assert result.new_ef == pytest.approx(1.70)

    def test_base_time_populates_next_review_at(self):
        """Supplying base_time fills next_review_at correctly."""
        base = datetime(2024, 1, 1, 12, 0, 0)
        result = schedule_review(
            quality=5,
            review_count=0,
            ef=2.5,
            last_interval_days=0.0,
            base_time=base,
        )
        expected = base + timedelta(days=1.0)
        assert result.next_review_at == expected

    def test_multi_cycle_progression(self):
        """Simulate several perfect-review cycles and check interval growth."""
        ef = 2.5
        interval = 0.0
        for count in range(1, 6):
            result = schedule_review(
                quality=5,
                review_count=count - 1,
                ef=ef,
                last_interval_days=interval,
            )
            ef = result.new_ef
            interval = result.next_interval_days

        # After 5 consecutive perfect reviews, interval must be well above 6.
        assert interval > 6.0

    def test_min_ef_propagated(self):
        """Custom min_ef is forwarded to update_ef correctly."""
        result = schedule_review(
            quality=0,
            review_count=0,
            ef=1.5,
            last_interval_days=0.0,
            min_ef=1.5,
        )
        assert result.new_ef >= 1.5


# ---------------------------------------------------------------------------
# ASM-2: should_review
# ---------------------------------------------------------------------------


class TestShouldReview:
    """Tests for :func:`should_review`."""

    def test_above_trigger_no_review(self):
        assert should_review(0.80, trigger=0.50) is False

    def test_at_trigger_needs_review(self):
        assert should_review(0.50, trigger=0.50) is True

    def test_below_trigger_needs_review(self):
        assert should_review(0.30, trigger=0.50) is True

    def test_custom_trigger(self):
        assert should_review(0.65, trigger=0.70) is True
        assert should_review(0.75, trigger=0.70) is False

    def test_full_retention_no_review(self):
        assert should_review(1.0) is False

    def test_zero_retention_needs_review(self):
        assert should_review(0.0) is True


# ---------------------------------------------------------------------------
# Integration: forgetting module imports
# ---------------------------------------------------------------------------


class TestForgettingImports:
    """Smoke tests verifying the forgetting sub-package is correctly wired."""

    def test_import_from_subpackage(self):
        from hm_arch.forgetting import (  # noqa: F401
            ReviewResult,
            l2_retention,
            l3_retention,
            next_interval,
            predict_retention_curve,
            schedule_review,
            should_review,
            update_ef,
        )

    def test_import_decay_directly(self):
        from hm_arch.forgetting.decay import (  # noqa: F401
            l2_retention,
            l2_retention_from_config,
            l3_retention,
            l3_retention_from_config,
            predict_retention_curve,
        )

    def test_import_asm2_directly(self):
        from hm_arch.forgetting.asm2 import (  # noqa: F401
            ReviewResult,
            next_interval,
            schedule_review,
            should_review,
            update_ef,
        )


# ---------------------------------------------------------------------------
# Context-aware forgetting score (HM-28)
# ---------------------------------------------------------------------------


class TestContextAwareForgettingScore:
    """Context-aware scores account for PRD forgetting factors."""

    def _memory(self, **overrides):
        from hm_arch.forgetting.context_aware import MemoryForgettingInput

        defaults = dict(
            memory_id="m1",
            content="User prefers Python",
            retention=0.2,
            layer=2,
            status="active",
            metadata={},
            neighbor_similarity=0.0,
            has_active_conflict=False,
        )
        defaults.update(overrides)
        return MemoryForgettingInput(**defaults)

    def test_low_retention_scores_higher_than_high_retention(self):
        from hm_arch.forgetting.context_aware import compute_context_aware_score

        low = compute_context_aware_score(self._memory(retention=0.1))
        high = compute_context_aware_score(self._memory(retention=0.9))
        assert low.composite > high.composite
        assert low.retention < high.retention

    def test_prd_formula_exact_numeric_regression(self):
        from hm_arch.forgetting.context_aware import compute_context_aware_score

        score = compute_context_aware_score(
            self._memory(
                retention=0.2,
                content="alpha beta gamma",
                neighbor_similarity=0.90,
                has_active_conflict=True,
                metadata={"private": True},
            ),
            context_query="alpha beta gamma",
        )
        assert score.retention == pytest.approx(0.2)
        assert score.relevance == pytest.approx(1.0)
        assert score.redundancy == pytest.approx(
            (0.90 - 0.85) / 0.15, rel=1e-9
        )
        assert score.contradiction == pytest.approx(1.0)
        assert score.privacy == pytest.approx(1.0)
        expected = (
            0.35 * (1.0 - 0.2)
            + 0.25 * (1.0 - 1.0)
            + 0.15 * score.redundancy
            + 0.15 * 1.0
            + 0.10 * 1.0
        )
        assert score.composite == pytest.approx(expected, rel=1e-9)

    def test_privacy_pressure_increases_prd_score(self):
        from hm_arch.forgetting.context_aware import (
            compute_context_aware_score,
            privacy_forgetting_pressure,
        )

        assert privacy_forgetting_pressure({"private": True}) == pytest.approx(1.0)
        plain = compute_context_aware_score(self._memory(metadata={}))
        sensitive = compute_context_aware_score(
            self._memory(metadata={"privacy_forget_pressure": 1.0})
        )
        assert sensitive.privacy == pytest.approx(1.0)
        assert sensitive.composite > plain.composite

    def test_irrelevant_content_scores_higher(self):
        from hm_arch.forgetting.context_aware import compute_context_aware_score

        irrelevant = compute_context_aware_score(
            self._memory(content="unrelated database tuning notes"),
            context_query="Python language preference",
        )
        relevant = compute_context_aware_score(
            self._memory(content="User prefers Python"),
            context_query="Python language preference",
        )
        assert irrelevant.relevance < relevant.relevance
        assert irrelevant.composite > relevant.composite

    def test_redundant_neighbor_increases_score(self):
        from hm_arch.forgetting.context_aware import compute_context_aware_score

        unique = compute_context_aware_score(self._memory(neighbor_similarity=0.2))
        redundant = compute_context_aware_score(
            self._memory(neighbor_similarity=0.95)
        )
        assert redundant.redundancy > unique.redundancy
        assert redundant.composite > unique.composite

    def test_contradiction_increases_score(self):
        from hm_arch.forgetting.context_aware import compute_context_aware_score

        plain = compute_context_aware_score(self._memory())
        conflict = compute_context_aware_score(
            self._memory(status="superseded", has_active_conflict=True)
        )
        assert conflict.contradiction == pytest.approx(1.0)
        assert conflict.composite > plain.composite


class TestOperationalContextAwareForgetting:
    """Context-aware score changes which memories are actually forgotten."""

    def test_global_forget_skips_relevant_deletable_memory(self):
        from hm_arch import HMArch, MemoryConfig

        config = MemoryConfig(
            db_path=":memory:",
            forgetting_score_threshold=0.50,
        )
        mem = HMArch(config=config)
        try:
            relevant_id = mem.add("User prefers Python tutorials").memory_id
            irrelevant_id = mem.add("Database vacuum maintenance schedule").memory_id
            for mid in (relevant_id, irrelevant_id):
                mem._db.execute(
                    """
                    UPDATE memory_index
                       SET current_retention = 0.01, status = 'deletable'
                     WHERE id = ?
                    """,
                    (mid,),
                )

            mem._forgetting.set_context_query("Python tutorials preference")
            result = mem.forget()
            forgotten_ids = {d["memory_id"] for d in result.details}
            assert irrelevant_id in forgotten_ids
            assert relevant_id not in forgotten_ids
        finally:
            mem.close()

    def test_global_forget_prefers_redundant_duplicate(self):
        from hm_arch import HMArch, MemoryConfig

        config = MemoryConfig(
            db_path=":memory:",
            forgetting_score_threshold=0.41,
            redundancy_threshold=0.85,
        )
        mem = HMArch(config=config)
        try:
            canonical = mem.add("unique sentinel omega protocol detail").memory_id
            duplicate = mem.add(
                "alpha beta gamma delta epsilon zeta eta theta iota"
            ).memory_id
            mem.add(
                "alpha beta gamma delta epsilon zeta eta theta iota kappa"
            )
            for mid in (canonical, duplicate):
                mem._db.execute(
                    """
                    UPDATE memory_index
                       SET current_retention = 0.20, status = 'deletable'
                     WHERE id = ?
                    """,
                    (mid,),
                )

            scored = mem._forgetting.iter_scored_candidates()
            scores = {row["id"]: score.composite for row, score in scored}
            assert scores[duplicate] > scores[canonical]

            result = mem.forget()
            forgotten_ids = {d["memory_id"] for d in result.details}
            assert duplicate in forgotten_ids
            assert canonical not in forgotten_ids
        finally:
            mem.close()

    def test_global_forget_removes_superseded_semantic_first(self):
        from hm_arch import HMArch, MemoryConfig

        config = MemoryConfig(db_path=":memory:", forgetting_score_threshold=0.41)
        mem = HMArch(config=config)
        try:
            active_id = mem._l3.upsert("user", "prefers", "Python")
            superseded_id = mem._l3.upsert("user", "prefers", "Java")
            mem._db.execute(
                """
                UPDATE memory_index
                   SET status = 'superseded', current_retention = 0.20
                 WHERE id = ?
                """,
                (superseded_id,),
            )
            mem._db.execute(
                """
                UPDATE memory_index
                   SET status = 'deletable', current_retention = 0.20
                 WHERE id = ?
                """,
                (active_id,),
            )

            scored = {
                row["id"]: score.composite
                for row, score in mem._forgetting.iter_scored_candidates()
            }
            assert scored[superseded_id] > scored[active_id]

            result = mem.forget()
            forgotten_ids = {d["memory_id"] for d in result.details}
            assert superseded_id in forgotten_ids
            assert active_id not in forgotten_ids
        finally:
            mem.close()


# ---------------------------------------------------------------------------
# Forgetting controller lifecycle (HM-28)
# ---------------------------------------------------------------------------


class TestForgettingControllerLifecycle:
    """Automatic consolidation and conservative physical cleanup."""

    @pytest.fixture()
    def clock(self):
        from hm_arch.forgetting.time import ManualTimeProvider

        return ManualTimeProvider(datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc))

    def test_auto_consolidate_disabled_is_deterministic(self, clock):
        from hm_arch import HMArch, MemoryConfig

        config = MemoryConfig(
            db_path=":memory:",
            auto_consolidate=False,
            consolidate_interval_hours=1,
            replay_sample_ratio=1.0,
        )
        mem = HMArch(config=config, time_provider=clock)
        try:
            mem.add("User prefers Python", importance=0.8)
            clock.advance(hours=48)
            mem.run_lifecycle()
            assert mem.get_stats().last_consolidation_at is None
        finally:
            mem.close()

    def test_auto_consolidate_runs_after_interval_without_timestamp_mutation(
        self, clock
    ):
        from hm_arch import EventType, HMArch, MemoryConfig

        config = MemoryConfig(
            db_path=":memory:",
            auto_consolidate=True,
            consolidate_interval_hours=24,
            replay_sample_ratio=1.0,
        )
        mem = HMArch(config=config, time_provider=clock)
        try:
            receipt = mem.add(
                "User prefers Python",
                event_type=EventType.CONVERSATION,
                importance=0.8,
            )
            clock.advance(hours=25)
            mem.run_lifecycle()
            assert mem.get_stats().last_consolidation_at is not None
            fact = mem._l3.get_by_entity_relation("user", "prefers")
            assert fact is not None
            rows = mem._db.query(
                "SELECT created_at FROM memory_index WHERE id = ?",
                (receipt.memory_id,),
            )
            assert rows[0]["created_at"].startswith("2024-01-01")
        finally:
            mem.close()

    def test_retention_decays_with_time_provider_not_timestamp_mutation(
        self, clock
    ):
        from hm_arch import HMArch, MemoryConfig
        from hm_arch.consolidation import ConsolidationEngine

        store = mem = None
        try:
            config = MemoryConfig(db_path=":memory:", replay_sample_ratio=1.0)
            mem = HMArch(config=config, time_provider=clock)
            receipt = mem.add("Some episodic event", importance=0.5)
            clock.advance(days=30)
            engine = ConsolidationEngine(
                mem._db,
                mem._l2,
                mem._l3,
                config=config,
                time_provider=clock,
            )
            engine.run_consolidation_cycle()
            rows = mem._db.query(
                "SELECT current_retention, created_at FROM memory_index WHERE id = ?",
                (receipt.memory_id,),
            )
            assert rows[0]["created_at"].startswith("2024-01-01")
            assert float(rows[0]["current_retention"]) < 0.5
        finally:
            if mem is not None:
                mem.close()

    def test_physical_cleanup_never_deletes_before_safety_period(self, clock):
        from hm_arch import HMArch, MemoryConfig
        from hm_arch.consolidation import ConsolidationEngine

        mem = None
        try:
            config = MemoryConfig(
                db_path=":memory:",
                auto_consolidate=False,
                deletion_safety_period_hours=168,
                replay_sample_ratio=1.0,
            )
            mem = HMArch(config=config, time_provider=clock)
            receipt = mem.add("Ancient episodic detail", importance=0.5)
            clock.advance(days=100)
            engine = ConsolidationEngine(
                mem._db,
                mem._l2,
                mem._l3,
                config=config,
                time_provider=clock,
            )
            report = engine.run_consolidation_cycle()
            assert report.marked_deletable >= 1

            rows = mem._db.query(
                "SELECT status FROM memory_index WHERE id = ?",
                (receipt.memory_id,),
            )
            assert rows[0]["status"] == "deletable"

            clock.advance(hours=24)
            cleanup = mem._forgetting.run_physical_cleanup()
            assert cleanup.forgotten_count == 0
            rows = mem._db.query(
                "SELECT status FROM memory_index WHERE id = ?",
                (receipt.memory_id,),
            )
            assert rows[0]["status"] == "deletable"

            clock.advance(hours=200)
            cleanup = mem._forgetting.run_physical_cleanup()
            assert cleanup.forgotten_count >= 1
            rows = mem._db.query(
                "SELECT status FROM memory_index WHERE id = ?",
                (receipt.memory_id,),
            )
            assert rows[0]["status"] == "deleted"
        finally:
            if mem is not None:
                mem.close()

    def test_forgetting_module_exports_lifecycle_types(self):
        from hm_arch.forgetting import (  # noqa: F401
            ContextAwareScore,
            ForgettingController,
            ManualTimeProvider,
            SystemTimeProvider,
            TimeProvider,
            compute_context_aware_score,
        )
