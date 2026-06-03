"""PRD performance contract constants for offline HM-Arch validation.

Values mirror the original HM-Arch developer PRD (see ``docs/spec.md`` source
reference) for single-process, local-fallback (SQLite + token-overlap vector)
operation. They are **not** distributed load-test SLOs.

Adjust only when the published PRD contract changes; benchmark results are
documented in ``docs/benchmarks.md``.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class PrdPerformanceTargets:
    """Latency and scale targets used by benchmark assertions."""

    l2_episode_count: int = 10_000
    l3_triple_count: int = 5_000
    add_p95_ms: float = 50.0
    search_p95_ms: float = 200.0
    consolidate_max_seconds: float = 120.0
    consolidate_replay_sample_ratio: float = 0.20
    add_warmup_iterations: int = 50
    add_sample_iterations: int = 200
    search_sample_iterations: int = 100


PRD_TARGETS = PrdPerformanceTargets()
