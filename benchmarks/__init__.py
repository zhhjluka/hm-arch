"""PRD scale and performance benchmarks for HM-Arch (HM-31 / MEM-31)."""

from .prd_targets import PRD_TARGETS
from .harness import BenchmarkReport, run_prd_benchmark_suite

__all__ = ["PRD_TARGETS", "BenchmarkReport", "run_prd_benchmark_suite"]
