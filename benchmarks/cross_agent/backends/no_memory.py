"""No-memory baseline backend."""

from __future__ import annotations

from pathlib import Path

from ..types import (
    BenchmarkQuery,
    BenchmarkRunConfig,
    IngestItem,
    IngestOutcome,
    OperationOutcome,
    ProviderDescriptor,
    RecallOutcome,
)
from .base import BaseMemoryBackend


class NoMemoryBackend(BaseMemoryBackend):
    """Baseline that never recalls or persists memory."""

    kind = "no_memory"

    def _setup_provider(self) -> None:
        return None

    def _teardown_provider(self) -> OperationOutcome:
        return OperationOutcome()

    def _ingest_item(self, item: IngestItem) -> IngestOutcome:
        _ = item
        return IngestOutcome()

    def _consolidate_provider(self) -> OperationOutcome:
        return OperationOutcome()

    def _reset_provider(self) -> OperationOutcome:
        return OperationOutcome()

    def _recall_query(self, query: BenchmarkQuery, *, top_k: int) -> RecallOutcome:
        _ = query, top_k
        return RecallOutcome(context="", retrieved_ids=(), recall_time_ms=0.0)

    def _provider_descriptor(self) -> ProviderDescriptor:
        return ProviderDescriptor(provider_id="no_memory", version=None, config={})
