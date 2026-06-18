"""No-memory baseline backend."""

from __future__ import annotations

import time
from pathlib import Path

from ..protocol import MemoryBackend
from ..types import BenchmarkQuery, BenchmarkRunConfig, IngestItem, RecallOutcome


class NoMemoryBackend:
    """Baseline that never recalls or persists memory."""

    kind = "no_memory"

    def open(self, storage_dir: Path, config: BenchmarkRunConfig) -> None:
        storage_dir.mkdir(parents=True, exist_ok=True)
        self._storage_dir = storage_dir

    def close(self) -> None:
        return None

    def ingest(self, item: IngestItem) -> None:
        return None

    def consolidate(self) -> None:
        return None

    def recall(self, query: BenchmarkQuery, *, top_k: int) -> RecallOutcome:
        t0 = time.perf_counter()
        _ = query, top_k
        elapsed = (time.perf_counter() - t0) * 1000.0
        return RecallOutcome(
            context="",
            retrieved_ids=(),
            recall_time_ms=elapsed,
            context_chars=0,
            hit_count=0,
        )
