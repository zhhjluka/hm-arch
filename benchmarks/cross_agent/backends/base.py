"""Shared base class and helpers for memory backend adapters."""

from __future__ import annotations

import time
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, Callable, TypeVar

from ..types import (
    BenchmarkQuery,
    BenchmarkRunConfig,
    IngestItem,
    IngestOutcome,
    OperationOutcome,
    OperationRecord,
    ProviderArtifacts,
    ProviderDescriptor,
    RecallOutcome,
)

T = TypeVar("T")


def measure_ms(fn: Callable[[], T]) -> tuple[T, float]:
    """Run *fn* and return its result with elapsed wall time in milliseconds."""
    t0 = time.perf_counter()
    result = fn()
    return result, (time.perf_counter() - t0) * 1000.0


class BaseMemoryBackend(ABC):
    """Track provider operations and enforce isolated per-run storage."""

    kind: str

    def __init__(self) -> None:
        self._storage_dir: Path | None = None
        self._config: BenchmarkRunConfig | None = None
        self._operations: list[OperationRecord] = []

    def open(self, storage_dir: Path, config: BenchmarkRunConfig) -> None:
        storage_dir.mkdir(parents=True, exist_ok=True)
        self._storage_dir = storage_dir
        self._config = config
        self._setup_provider()

    def close(self) -> OperationOutcome:
        try:
            outcome, latency_ms = measure_ms(self._teardown_provider)
            self._record("teardown", latency_ms, outcome)
            return outcome
        except Exception as exc:  # noqa: BLE001
            outcome = OperationOutcome(
                latency_ms=0.0,
                failure_count=1,
                error=str(exc),
            )
            self._record("teardown", 0.0, outcome)
            return outcome
        finally:
            self._storage_dir = None
            self._config = None

    def ingest(self, item: IngestItem) -> IngestOutcome:
        try:
            outcome, latency_ms = measure_ms(lambda: self._ingest_item(item))
            self._record(
                "ingest",
                latency_ms,
                OperationOutcome(
                    latency_ms=latency_ms,
                    failure_count=outcome.failure_count,
                    error=outcome.error,
                ),
                ingested_count=len(outcome.ingested_ids),
            )
            outcome.ingest_time_ms = latency_ms
            return outcome
        except Exception as exc:  # noqa: BLE001
            outcome = IngestOutcome(
                ingest_time_ms=0.0,
                failure_count=1,
                error=str(exc),
            )
            self._record(
                "ingest",
                0.0,
                OperationOutcome(latency_ms=0.0, failure_count=1, error=str(exc)),
            )
            return outcome

    def consolidate(self) -> OperationOutcome:
        try:
            outcome, latency_ms = measure_ms(self._consolidate_provider)
            self._record("consolidate", latency_ms, outcome)
            return outcome
        except Exception as exc:  # noqa: BLE001
            outcome = OperationOutcome(latency_ms=0.0, failure_count=1, error=str(exc))
            self._record("consolidate", 0.0, outcome)
            return outcome

    def reset(self) -> OperationOutcome:
        try:
            outcome, latency_ms = measure_ms(self._reset_provider)
            self._record("reset", latency_ms, outcome)
            return outcome
        except Exception as exc:  # noqa: BLE001
            outcome = OperationOutcome(latency_ms=0.0, failure_count=1, error=str(exc))
            self._record("reset", 0.0, outcome)
            return outcome

    def recall(self, query: BenchmarkQuery, *, top_k: int) -> RecallOutcome:
        t0 = time.perf_counter()
        try:
            outcome = self._recall_query(query, top_k=top_k)
            elapsed = (time.perf_counter() - t0) * 1000.0
            outcome.recall_time_ms = elapsed
            outcome.context_chars = len(outcome.context)
            self._record(
                "recall",
                elapsed,
                OperationOutcome(
                    latency_ms=elapsed,
                    failure_count=outcome.failure_count,
                    error=outcome.error,
                ),
                context_chars=outcome.context_chars,
                hit_count=outcome.hit_count,
            )
            return outcome
        except Exception as exc:  # noqa: BLE001
            elapsed = (time.perf_counter() - t0) * 1000.0
            outcome = RecallOutcome(
                context="",
                retrieved_ids=(),
                recall_time_ms=elapsed,
                failure_count=1,
                error=str(exc),
            )
            self._record(
                "recall",
                elapsed,
                OperationOutcome(latency_ms=elapsed, failure_count=1, error=str(exc)),
            )
            return outcome

    def provider_artifacts(self) -> ProviderArtifacts:
        return ProviderArtifacts(
            provider=self._provider_descriptor(),
            operations=list(self._operations),
        )

    def storage_dir(self) -> Path:
        if self._storage_dir is None:
            raise RuntimeError(f"{self.__class__.__name__}.open() was not called")
        return self._storage_dir

    def run_config(self) -> BenchmarkRunConfig:
        if self._config is None:
            raise RuntimeError(f"{self.__class__.__name__}.open() was not called")
        return self._config

    @abstractmethod
    def _setup_provider(self) -> None:
        """Initialize provider resources in the isolated storage directory."""

    @abstractmethod
    def _teardown_provider(self) -> OperationOutcome:
        """Release provider resources."""

    @abstractmethod
    def _ingest_item(self, item: IngestItem) -> IngestOutcome:
        """Provider-specific ingest implementation."""

    @abstractmethod
    def _consolidate_provider(self) -> OperationOutcome:
        """Provider-specific consolidation."""

    @abstractmethod
    def _reset_provider(self) -> OperationOutcome:
        """Provider-specific reset."""

    @abstractmethod
    def _recall_query(self, query: BenchmarkQuery, *, top_k: int) -> RecallOutcome:
        """Provider-specific recall implementation."""

    @abstractmethod
    def _provider_descriptor(self) -> ProviderDescriptor:
        """Return provider identity for artifact export."""

    def _record(
        self,
        operation: str,
        latency_ms: float,
        outcome: OperationOutcome,
        *,
        context_chars: int = 0,
        hit_count: int = 0,
        ingested_count: int = 0,
    ) -> None:
        self._operations.append(
            OperationRecord(
                operation=operation,
                latency_ms=latency_ms,
                error=outcome.error,
                context_chars=context_chars,
                hit_count=hit_count,
                ingested_count=ingested_count,
            )
        )

    def _namespace(self) -> str:
        config = self.run_config()
        return f"{config.family.value}-{config.agent.value}-{config.seed}"
