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
    use_mock_agent: bool = True
    agent_executable: str | None = None
    agent_timeout_s: float = 120.0
    dataset_id: str | None = None
    dataset_version: str | None = None
    max_conversations: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "family": self.family.value,
            "agent": self.agent.value,
            "backend": self.backend.value,
            "seed": self.seed,
            "run_id": self.run_id,
            "top_k": self.top_k,
            "resume": self.resume,
            "use_mock_agent": self.use_mock_agent,
            "agent_executable": self.agent_executable,
            "agent_timeout_s": self.agent_timeout_s,
            "dataset_id": self.dataset_id,
            "dataset_version": self.dataset_version,
            "max_conversations": self.max_conversations,
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
            use_mock_agent=bool(data.get("use_mock_agent", True)),
            agent_executable=data.get("agent_executable"),
            agent_timeout_s=float(data.get("agent_timeout_s", 120.0)),
            dataset_id=data.get("dataset_id"),
            dataset_version=data.get("dataset_version"),
            max_conversations=data.get("max_conversations"),
        )


@dataclass
class RecallOutcome:
    """Result of a memory recall operation."""

    context: str
    retrieved_ids: tuple[str, ...]
    recall_time_ms: float
    failure_count: int = 0
    error: str | None = None
    context_chars: int = 0
    hit_count: int = 0
    agent_managed: bool = False


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
    input_token_source: str = "estimated"
    output_token_source: str = "estimated"
    metadata: dict[str, Any] = field(default_factory=dict)


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
    input_token_source: str = "estimated"
    output_token_source: str = "estimated"
    retrieved_ids: tuple[str, ...] = ()
    expected_memory_ids: tuple[str, ...] = ()
    recall_context_chars: int = 0
    recall_hit_count: int = 0
    agent_managed: bool = False
    failure_reason: str | None = None
    failure_category: str | None = None
    recall_failure_reason: str | None = None
    agent_failure_reason: str | None = None
    agent_exit_code: int | None = None
    agent_timed_out: bool | None = None
    agent_metadata: dict[str, Any] = field(default_factory=dict)

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
    agent_metadata: dict[str, Any] = field(default_factory=dict)
    compatibility: dict[str, str] = field(default_factory=dict)
    dataset: dict[str, Any] = field(default_factory=dict)
    category_aggregates: dict[str, Any] = field(default_factory=dict)
    timing_aggregates: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "run_id": self.run_id,
            "config": self.config.to_dict(),
            "storage_dir": self.storage_dir,
            "phases_completed": self.phases_completed,
            "queries": [q.to_dict() for q in self.queries],
            "aggregates": self.aggregates.to_dict(),
            "environment": self.environment,
            "agent_metadata": self.agent_metadata,
            "compatibility": self.compatibility,
        }
        if self.dataset:
            payload["dataset"] = self.dataset
        if self.category_aggregates:
            payload["category_aggregates"] = self.category_aggregates
        if self.timing_aggregates:
            payload["timing_aggregates"] = self.timing_aggregates
        return payload
