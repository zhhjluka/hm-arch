"""Agent-native memory backend adapter for cross-agent benchmarks."""

from __future__ import annotations

import time
from pathlib import Path
from typing import Protocol, runtime_checkable

from ..types import BenchmarkQuery, BenchmarkRunConfig, IngestItem, RecallOutcome


@runtime_checkable
class AgentNativeMemoryBridge(Protocol):
    """Optional bridge supplied by an agent runner for native-memory mode."""

    def ingest(self, item: IngestItem) -> tuple[str, ...]:
        """Persist a turn using the agent's built-in memory; return memory ids."""

    def recall(self, query: BenchmarkQuery, *, top_k: int) -> tuple[str, str, int]:
        """Recall context, retrieved ids, and hit count from native memory."""

    def consolidate(self) -> None:
        """Trigger the agent's native consolidation, if any."""


class NativeMemoryBackend:
    """Benchmark backend that delegates to an agent-owned native memory bridge.

    When no bridge is supplied, ingest/recall remain no-ops but are tagged with
  ``agent_managed=True`` so downstream reports can distinguish the mode from the
    no-memory control.
    """

    kind = "native_memory"

    def __init__(self, *, bridge: AgentNativeMemoryBridge | None = None) -> None:
        self._bridge = bridge
        self._agent_managed = True

    def open(self, storage_dir: Path, config: BenchmarkRunConfig) -> None:
        storage_dir.mkdir(parents=True, exist_ok=True)
        _ = config

    def close(self) -> None:
        self._bridge = None

    def ingest(self, item: IngestItem) -> None:
        if self._bridge is not None:
            self._bridge.ingest(item)

    def consolidate(self) -> None:
        if self._bridge is not None:
            self._bridge.consolidate()

    def recall(self, query: BenchmarkQuery, *, top_k: int) -> RecallOutcome:
        t0 = time.perf_counter()
        if self._bridge is not None:
            context, retrieved_ids, hit_count = self._bridge.recall(query, top_k=top_k)
            elapsed = (time.perf_counter() - t0) * 1000.0
            return RecallOutcome(
                context=context,
                retrieved_ids=retrieved_ids,
                recall_time_ms=elapsed,
                context_chars=len(context),
                hit_count=hit_count,
                agent_managed=True,
            )

        elapsed = (time.perf_counter() - t0) * 1000.0
        return RecallOutcome(
            context="",
            retrieved_ids=(),
            recall_time_ms=elapsed,
            context_chars=0,
            hit_count=0,
            agent_managed=True,
        )
