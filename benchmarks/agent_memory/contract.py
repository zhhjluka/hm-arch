"""Cross-agent memory benchmark backend contract (HM-72 / MEM-73)."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Protocol, runtime_checkable


class MemoryProviderId(str, Enum):
    """Supported external memory providers for benchmark runs."""

    NO_MEMORY = "no-memory"
    HM_ARCH = "hm-arch"
    MEM0 = "mem0"
    OPENVIKING = "openviking"
    NATIVE_MEMORY = "native-memory"


class AgentId(str, Enum):
    """Agents participating in the cross-agent benchmark matrix."""

    OPENCLAW = "openclaw"
    HERMES = "hermes"
    CLAUDE_CODE = "claude-code"
    CODEX = "codex"


@dataclass(frozen=True)
class MemoryBackendRunConfig:
    """Isolated configuration for one benchmark backend instance."""

    run_id: str
    namespace: str
    workspace_root: Path
    agent_id: AgentId
    provider_id: MemoryProviderId
    recall_top_k: int = 5
    max_context_chars: int = 8000
    extra: dict[str, Any] = field(default_factory=dict)

    def storage_dir(self) -> Path:
        """Return the isolated on-disk namespace for this run."""
        return self.workspace_root / self.run_id / self.namespace / self.provider_id.value


@dataclass(frozen=True)
class IngestTurn:
    """Normalized conversation turn written by benchmark fixtures."""

    user_message: str
    agent_message: str
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class ProviderOperationMetrics:
    """Provider-side latency and payload size for one backend operation."""

    latency_ms: float
    context_chars: int = 0
    hit_count: int = 0
    ingested_count: int = 0


@dataclass
class RecallResult:
    """Normalized recall response from any memory backend."""

    ok: bool
    context: str
    metrics: ProviderOperationMetrics
    agent_managed: bool = False
    error: str | None = None


@dataclass
class IngestResult:
    """Normalized ingest response from any memory backend."""

    ok: bool
    memory_ids: list[str]
    metrics: ProviderOperationMetrics
    agent_managed: bool = False
    error: str | None = None


@dataclass
class ConsolidateResult:
    """Normalized consolidation response from any memory backend."""

    ok: bool
    metrics: ProviderOperationMetrics
    extracted_semantics: int = 0
    error: str | None = None


class UnsupportedCombinationError(ValueError):
    """Raised when a provider/agent pair is not supported by the benchmark matrix."""


@runtime_checkable
class MemoryBackend(Protocol):
    """Comparable memory backend contract for cross-agent benchmarks."""

    provider_id: MemoryProviderId
    agent_id: AgentId
    config: MemoryBackendRunConfig

    def setup(self) -> None:
        """Prepare an isolated store/namespace for the run."""

    def ingest(self, turn: IngestTurn) -> IngestResult:
        """Persist one normalized conversation turn."""

    def recall(self, query: str, *, top_k: int | None = None) -> RecallResult:
        """Retrieve provider context for a benchmark query."""

    def consolidate(self) -> ConsolidateResult:
        """Run an optional provider-side consolidation phase."""

    def reset(self) -> None:
        """Clear provider state while keeping the backend configured."""

    def teardown(self) -> None:
        """Release resources and remove isolated storage when possible."""
