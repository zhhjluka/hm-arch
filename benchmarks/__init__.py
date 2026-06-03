"""PRD scale and performance benchmarks for HM-Arch (HM-31 / MEM-31)."""

from .harness import (
    BenchmarkReport,
    passes_strict_greater,
    passes_strict_less,
    run_prd_benchmark_suite,
)
from .prd_targets import PRD_TARGETS

__all__ = [
    "PRD_TARGETS",
    "BenchmarkReport",
    "passes_strict_greater",
    "passes_strict_less",
    "run_prd_benchmark_suite",
]
