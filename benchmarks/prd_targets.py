"""PRD performance contract constants for offline HM-Arch validation.

The original HM-Arch developer PRD defines **two** performance tables:

1. **Test benchmark** (acceptance): add p95 ≤50ms, search p95 ≤100ms @10k L2,
   consolidate ≤60s @10k L2, storage <500MB for 10k L2 + 5k L3.
2. **Week 9 optimization** (stretch): add <30ms, search <50ms, consolidate <5s.

Both are reported in benchmark output; assertions use the test-benchmark table
unless noted otherwise. See ``docs/benchmarks.md``.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class PrdTestBenchmarkTargets:
    """PRD § test-benchmark table (primary acceptance contract)."""

    add_p95_ms: float = 50.0
    search_p95_ms: float = 100.0
    consolidate_max_seconds: float = 60.0
    storage_max_mb: float = 500.0


@dataclass(frozen=True)
class PrdWeek9OptimizationTargets:
    """PRD Week 9 optimization targets (stretch goals, reported separately)."""

    add_p95_ms: float = 30.0
    search_p95_ms: float = 50.0
    consolidate_max_seconds: float = 5.0


@dataclass(frozen=True)
class PrdPerformanceTargets:
    """Latency, scale, and scenario targets used by benchmark assertions."""

    l2_episode_count: int = 10_000
    l3_triple_count: int = 5_000
    consolidate_replay_sample_ratio: float = 0.20
    add_warmup_iterations: int = 50
    add_sample_iterations: int = 200
    search_sample_iterations: int = 100
    seven_day_conversations_per_day: int = 50
    seven_day_consolidations: int = 7
    seven_day_min_semantic_accuracy: float = 0.80
    seven_day_replay_sample_ratio: float = 1.0
    l2_retention_30d_reference: float = 0.26
    l4_archive_fraction_tolerance: float = 0.05
    l4_archive_old_fraction: float = 0.74
    l4_archive_old_days: int = 90
    l4_archive_young_days: int = 30
    test_benchmark: PrdTestBenchmarkTargets = field(
        default_factory=PrdTestBenchmarkTargets
    )
    week9_optimization: PrdWeek9OptimizationTargets = field(
        default_factory=PrdWeek9OptimizationTargets
    )


PRD_TARGETS = PrdPerformanceTargets()
