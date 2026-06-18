"""Common interfaces for agent and memory provider adapters."""

from __future__ import annotations

from pathlib import Path
from typing import Protocol, runtime_checkable

from .types import (
    AgentOutcome,
    BenchmarkQuery,
    BenchmarkRunConfig,
    IngestItem,
    RecallOutcome,
)


@runtime_checkable
class MemoryBackend(Protocol):
    """Memory provider adapter executed by the benchmark harness.

    Implementations receive an isolated per-run storage directory and must not
    share state across runs.
    """

    kind: str

    def open(self, storage_dir: Path, config: BenchmarkRunConfig) -> None:
        """Prepare isolated storage for this run."""

    def close(self) -> None:
        """Release resources for this run."""

    def ingest(self, item: IngestItem) -> None:
        """Persist one ingest event into durable memory."""

    def consolidate(self) -> None:
        """Optional offline consolidation between ingest and query phases."""

    def recall(self, query: BenchmarkQuery, *, top_k: int) -> RecallOutcome:
        """Retrieve memory relevant to *query*."""


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
