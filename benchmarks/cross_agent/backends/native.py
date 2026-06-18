"""Agent-native memory backend — delegates to the agent runner bridge."""

from __future__ import annotations

from ..protocol import AgentNativeMemoryBridge
from ..types import (
    BenchmarkQuery,
    IngestItem,
    IngestOutcome,
    OperationOutcome,
    ProviderDescriptor,
    RecallOutcome,
    UnsupportedCombinationError,
)
from .base import BaseMemoryBackend


class NativeMemoryBackend(BaseMemoryBackend):
    """Delegates to the selected agent runner's native-memory bridge."""

    kind = "native_memory"

    def __init__(self, *, bridge: AgentNativeMemoryBridge | None = None) -> None:
        super().__init__()
        self._bridge = bridge

    def _setup_provider(self) -> None:
        if self._bridge is None:
            agent = self.run_config().agent.value
            raise UnsupportedCombinationError(
                f"Native memory for agent {agent!r} requires a real native-memory "
                "bridge from the agent runner; no generic fallback is permitted."
            )

    def _teardown_provider(self) -> OperationOutcome:
        self._bridge = None
        return OperationOutcome()

    def _ingest_item(self, item: IngestItem) -> IngestOutcome:
        assert self._bridge is not None
        return self._bridge.ingest(item)

    def _consolidate_provider(self) -> OperationOutcome:
        assert self._bridge is not None
        return self._bridge.consolidate()

    def _reset_provider(self) -> OperationOutcome:
        assert self._bridge is not None
        if hasattr(self._bridge, "reset"):
            reset = getattr(self._bridge, "reset")
            if callable(reset):
                return reset()
        return OperationOutcome()

    def _recall_query(self, query: BenchmarkQuery, *, top_k: int) -> RecallOutcome:
        assert self._bridge is not None
        return self._bridge.recall(query, top_k=top_k)

    def _provider_descriptor(self) -> ProviderDescriptor:
        config = self.run_config()
        return ProviderDescriptor(
            provider_id="native_memory",
            version=None,
            config={
                "agent": config.agent.value,
                "bridge": type(self._bridge).__name__ if self._bridge else None,
            },
            simulated=False,
        )
