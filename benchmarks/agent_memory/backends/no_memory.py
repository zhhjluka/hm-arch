"""No-memory benchmark control backend."""

from __future__ import annotations

from ..contract import (
    ConsolidateResult,
    IngestResult,
    IngestTurn,
    MemoryProviderId,
    ProviderOperationMetrics,
    RecallResult,
)
from ..metrics import measure_ms
from .base import BaseMemoryBackend


class NoMemoryBackend(BaseMemoryBackend):
    """Control backend that never stores or recalls external context."""

    provider_id = MemoryProviderId.NO_MEMORY

    def _setup_provider(self) -> None:
        return None

    def _teardown_provider(self) -> None:
        return None

    def ingest(self, turn: IngestTurn) -> IngestResult:
        self._require_ready()

        def _noop() -> list[str]:
            return []

        memory_ids, latency_ms = measure_ms(_noop)
        return IngestResult(
            ok=True,
            memory_ids=memory_ids,
            metrics=ProviderOperationMetrics(
                latency_ms=latency_ms,
                ingested_count=0,
            ),
        )

    def recall(self, query: str, *, top_k: int | None = None) -> RecallResult:
        self._require_ready()

        def _empty() -> str:
            return ""

        context, latency_ms = measure_ms(_empty)
        return RecallResult(
            ok=True,
            context=context,
            metrics=ProviderOperationMetrics(
                latency_ms=latency_ms,
                context_chars=0,
                hit_count=0,
            ),
        )

    def consolidate(self) -> ConsolidateResult:
        self._require_ready()

        def _noop() -> int:
            return 0

        extracted, latency_ms = measure_ms(_noop)
        return ConsolidateResult(
            ok=True,
            metrics=ProviderOperationMetrics(latency_ms=latency_ms),
            extracted_semantics=extracted,
        )
