"""Agent-native memory backend contract for benchmark runners."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

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


@runtime_checkable
class AgentNativeMemoryBridge(Protocol):
    """Optional bridge supplied by an AgentRunner for native-memory mode."""

    def ingest(self, turn: IngestTurn) -> IngestResult:
        """Persist a turn using the agent's built-in memory."""

    def recall(self, query: str, *, top_k: int | None = None) -> RecallResult:
        """Recall context from the agent's built-in memory."""

    def consolidate(self) -> ConsolidateResult:
        """Trigger the agent's native consolidation, if any."""


class NativeMemoryBackend(BaseMemoryBackend):
    """Benchmark backend that delegates to an agent-owned native memory bridge.

    When no bridge is supplied, ingest/recall remain no-ops but are tagged with
  ``agent_managed=True`` so downstream reports can distinguish the mode from the
    no-memory control.
    """

    provider_id = MemoryProviderId.NATIVE_MEMORY

    def __init__(self, config, *, bridge: AgentNativeMemoryBridge | None = None) -> None:
        super().__init__(config)
        self._bridge = bridge

    def _setup_provider(self) -> None:
        return None

    def _teardown_provider(self) -> None:
        self._bridge = None

    def ingest(self, turn: IngestTurn) -> IngestResult:
        self._require_ready()
        if self._bridge is not None:
            result = self._bridge.ingest(turn)
            result.agent_managed = True
            return result

        def _noop() -> list[str]:
            return []

        memory_ids, latency_ms = measure_ms(_noop)
        return IngestResult(
            ok=True,
            memory_ids=memory_ids,
            agent_managed=True,
            metrics=ProviderOperationMetrics(
                latency_ms=latency_ms,
                ingested_count=0,
            ),
        )

    def recall(self, query: str, *, top_k: int | None = None) -> RecallResult:
        self._require_ready()
        if self._bridge is not None:
            result = self._bridge.recall(query, top_k=top_k)
            result.agent_managed = True
            return result

        def _empty() -> str:
            return ""

        context, latency_ms = measure_ms(_empty)
        return RecallResult(
            ok=True,
            context=context,
            agent_managed=True,
            metrics=ProviderOperationMetrics(
                latency_ms=latency_ms,
                context_chars=0,
                hit_count=0,
            ),
        )

    def consolidate(self) -> ConsolidateResult:
        self._require_ready()
        if self._bridge is not None:
            return self._bridge.consolidate()

        def _noop() -> int:
            return 0

        extracted, latency_ms = measure_ms(_noop)
        return ConsolidateResult(
            ok=True,
            metrics=ProviderOperationMetrics(latency_ms=latency_ms),
            extracted_semantics=extracted,
        )
