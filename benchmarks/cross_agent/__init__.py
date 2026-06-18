"""Cross-agent memory benchmark harness (HM-71 / MEM-68).

Reproducible evaluation of LoCoMo, tau2-bench, and HotpotQA across agents and
memory backends. See ``docs/cross-agent-benchmarks.md``.
"""

from .protocol import AgentNativeMemoryBridge, AgentRunner, MemoryBackend
from .runner import CrossAgentBenchmarkHarness, run_cross_agent_benchmark
from .types import (
    AgentKind,
    BenchmarkFamily,
    BenchmarkRunConfig,
    BenchmarkRunResult,
    MemoryBackendKind,
    ProviderUnavailableError,
    QueryRecord,
    RunPhase,
    UnsupportedCombinationError,
)

__all__ = [
    "AgentKind",
    "AgentNativeMemoryBridge",
    "AgentRunner",
    "BenchmarkFamily",
    "BenchmarkRunConfig",
    "BenchmarkRunResult",
    "CrossAgentBenchmarkHarness",
    "MemoryBackend",
    "MemoryBackendKind",
    "ProviderUnavailableError",
    "QueryRecord",
    "RunPhase",
    "UnsupportedCombinationError",
    "run_cross_agent_benchmark",
]
