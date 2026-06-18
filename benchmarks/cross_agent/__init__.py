"""Cross-agent memory benchmark harness (HM-71 / MEM-68).

Reproducible evaluation of LoCoMo, tau2-bench, and HotpotQA across agents and
memory backends. See ``docs/cross-agent-benchmarks.md``.
"""

from .compatibility import (
    UnsupportedCombinationError,
    assert_supported,
    compatibility_cell,
    supported_pairs,
    unsupported_pairs,
)
from .protocol import AgentRunner, MemoryBackend
from .runner import CrossAgentBenchmarkHarness, run_cross_agent_benchmark
from .types import (
    AgentKind,
    BenchmarkFamily,
    BenchmarkRunConfig,
    BenchmarkRunResult,
    MemoryBackendKind,
    QueryRecord,
    RunPhase,
)

__all__ = [
    "AgentKind",
    "AgentRunner",
    "BenchmarkFamily",
    "BenchmarkRunConfig",
    "BenchmarkRunResult",
    "CrossAgentBenchmarkHarness",
    "MemoryBackend",
    "MemoryBackendKind",
    "QueryRecord",
    "RunPhase",
    "UnsupportedCombinationError",
    "assert_supported",
    "compatibility_cell",
    "run_cross_agent_benchmark",
    "supported_pairs",
    "unsupported_pairs",
]
