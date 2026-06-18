"""Common interfaces for agent and memory provider adapters."""

from __future__ import annotations

from pathlib import Path
from typing import Protocol, runtime_checkable

from .types import (
    AgentOutcome,
    BenchmarkQuery,
    BenchmarkRunConfig,
    IngestItem,
    IngestOutcome,
    OperationOutcome,
    ProviderArtifacts,
    RecallOutcome,
)


@runtime_checkable
class AgentNativeMemoryBridge(Protocol):
    """Bridge supplied by an agent runner for native-memory benchmark mode."""

    def ingest(self, item: IngestItem) -> IngestOutcome:
        """Persist one turn using the agent's built-in memory."""

    def recall(self, query: BenchmarkQuery, *, top_k: int) -> RecallOutcome:
        """Recall context from the agent's built-in memory."""

    def consolidate(self) -> OperationOutcome:
        """Trigger native consolidation when supported."""


@runtime_checkable
class MemoryBackend(Protocol):
    """Memory provider adapter executed by the benchmark harness.

    Implementations receive an isolated per-run storage directory and must not
    share state across runs.
    """

    kind: str

    def open(self, storage_dir: Path, config: BenchmarkRunConfig) -> None:
        """Prepare isolated storage for this run."""

    def close(self) -> OperationOutcome:
        """Release resources for this run (teardown)."""

    def ingest(self, item: IngestItem) -> IngestOutcome:
        """Persist one ingest event into durable memory."""

    def consolidate(self) -> OperationOutcome:
        """Optional offline consolidation between ingest and query phases."""

    def reset(self) -> OperationOutcome:
        """Clear durable memory while keeping the run workspace."""

    def recall(self, query: BenchmarkQuery, *, top_k: int) -> RecallOutcome:
        """Retrieve memory relevant to *query*."""

    def provider_artifacts(self) -> ProviderArtifacts:
        """Export provider identity and per-operation latency/error records."""


@runtime_checkable
class AgentRunner(Protocol):
    """Host agent adapter that answers benchmark queries."""

    kind: str

    def answer(
        self,
        query: BenchmarkQuery,
        *,
        recalled_context: str,
        seed: int,
    ) -> AgentOutcome:
        """Produce an answer using the recalled memory context."""

    def native_memory_bridge(self) -> AgentNativeMemoryBridge | None:
        """Return the agent's native-memory bridge, if this agent supports it."""
