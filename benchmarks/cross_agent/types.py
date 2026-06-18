"""Shared types for the cross-agent memory benchmark harness."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any


class BenchmarkFamily(str, Enum):
    """Supported benchmark dataset families."""

    LOCOMO = "locomo"
    TAU2_BENCH = "tau2_bench"
    HOTPOTQA = "hotpotqa"


class MemoryBackendKind(str, Enum):
    """Registered memory backend providers."""

    NO_MEMORY = "no_memory"
    NATIVE_MEMORY = "native_memory"
    HM_ARCH = "hm_arch"
    OPENVIKING = "openviking"
    MEM0 = "mem0"


class AgentKind(str, Enum):
    """Registered host agent adapters."""

    OPENCLAW = "openclaw"
    HERMES = "hermes"
    CLAUDE_CODE = "claude_code"
    CODEX = "codex"


class RunPhase(str, Enum):
    """Lifecycle phases executed by the harness."""

    SETUP = "setup"
    INGEST = "ingest"
    CONSOLIDATE = "consolidate"
    QUERY = "query"
    EVALUATE = "evaluate"
    CHECKPOINT = "checkpoint"
    TEARDOWN = "teardown"


@dataclass(frozen=True)
class IngestItem:
    """A single memory-ingest event (conversation turn, document, or task log)."""

    item_id: str
    content: str
    session_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class BenchmarkQuery:
    """One evaluable query with optional ground truth for scoring."""

    query_id: str
    question: str
    expected_answer: str | None = None
    expected_memory_ids: tuple[str, ...] = ()
    supporting_facts: tuple[str, ...] = ()
    task_success_criteria: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class SyntheticFixture:
    """Offline fixture covering ingest corpus and eval queries for one family."""

    family: BenchmarkFamily
    ingest_items: tuple[IngestItem, ...]
    queries: tuple[BenchmarkQuery, ...]
    consolidate_after_ingest: bool = True


@dataclass(frozen=True)
class BenchmarkRunConfig:
    """Configuration for a single harness run."""

    family: BenchmarkFamily
    agent: AgentKind
    backend: MemoryBackendKind
    seed: int = 0
    run_id: str | None = None
    top_k: int = 5
    resume: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "family": self.family.value,
            "agent": self.agent.value,
            "backend": self.backend.value,
            "seed": self.seed,
            "run_id": self.run_id,
            "top_k": self.top_k,
            "resume": self.resume,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> BenchmarkRunConfig:
        return cls(
            family=BenchmarkFamily(data["family"]),
            agent=AgentKind(data["agent"]),
            backend=MemoryBackendKind(data["backend"]),
            seed=int(data["seed"]),
            run_id=data.get("run_id"),
            top_k=int(data.get("top_k", 5)),
            resume=bool(data.get("resume", True)),
        )


@dataclass
class RecallOutcome:
    """Result of a memory recall operation."""

    context: str
    retrieved_ids: tuple[str, ...]
    recall_time_ms: float
    failure_count: int = 0
    error: str | None = None


@dataclass
class AgentOutcome:
    """Result of an agent answer step."""

    answer: str
    task_success: bool | None
    input_tokens: int
    output_tokens: int
    agent_time_ms: float
    failure_count: int = 0
    error: str | None = None


@dataclass
class QueryRecord:
    """Per-query metrics emitted by the harness."""

    query_id: str
    family: str
    question: str
    expected_answer: str | None
    prediction: str | None
    accuracy: float | None
    task_success: bool | None
    retrieval_hit_rate: float | None
    recall_time_ms: float
    agent_time_ms: float
    query_time_ms: float
    input_tokens: int
    output_tokens: int
    failure_count: int
    retrieved_ids: tuple[str, ...] = ()
    expected_memory_ids: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class AggregateMetrics:
    """Roll-up metrics for a completed or partial run."""

    query_count: int
    completed_query_count: int
    mean_accuracy: float | None
    task_success_rate: float | None
    mean_retrieval_hit_rate: float | None
    mean_query_time_ms: float
    total_input_tokens: int
    total_output_tokens: int
    total_failure_count: int

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class BenchmarkRunResult:
    """Structured result for one harness run."""

    run_id: str
    config: BenchmarkRunConfig
    storage_dir: str
    phases_completed: list[str]
    queries: list[QueryRecord]
    aggregates: AggregateMetrics
    environment: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "config": self.config.to_dict(),
            "storage_dir": self.storage_dir,
            "phases_completed": self.phases_completed,
            "queries": [q.to_dict() for q in self.queries],
            "aggregates": self.aggregates.to_dict(),
            "environment": self.environment,
        }
