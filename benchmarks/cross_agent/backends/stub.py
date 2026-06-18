"""Placeholder backend for providers not yet wired in this repository."""

from __future__ import annotations

from pathlib import Path

from ..types import BenchmarkQuery, BenchmarkRunConfig, IngestItem, MemoryBackendKind, RecallOutcome


class StubMemoryBackend:
    """Registers a backend slot; raises until an external adapter is installed."""

    def __init__(self, kind: MemoryBackendKind) -> None:
        self.kind = kind.value
        self._kind = kind

    def open(self, storage_dir: Path, config: BenchmarkRunConfig) -> None:
        _ = storage_dir, config
        raise NotImplementedError(
            f"Memory backend {self._kind.value!r} is not implemented in this repo. "
            "Register a custom adapter via register_memory_backend()."
        )

    def close(self) -> None:
        return None

    def ingest(self, item: IngestItem) -> None:
        raise NotImplementedError(self.kind)

    def consolidate(self) -> None:
        raise NotImplementedError(self.kind)

    def recall(self, query: BenchmarkQuery, *, top_k: int) -> RecallOutcome:
        raise NotImplementedError(self.kind)
