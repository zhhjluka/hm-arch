"""HM-Arch benchmark backend using public integration runtime APIs."""

from __future__ import annotations

import os
from contextlib import contextmanager
from typing import Iterator

from hm_arch.integrations.cli.runtime import (
    execute_consolidate,
    execute_recall,
    execute_record,
)
from hm_arch.integrations.config import IntegrationConfig
from hm_arch.integrations.protocol import (
    ConsolidateRequest,
    RecallRequest,
    RecordRequest,
)

from ..contract import (
    ConsolidateResult,
    IngestResult,
    IngestTurn,
    MemoryBackendRunConfig,
    MemoryProviderId,
    ProviderOperationMetrics,
    RecallResult,
)
from ..metrics import measure_ms
from .base import BaseMemoryBackend


class HMArchMemoryBackend(BaseMemoryBackend):
    """Benchmark adapter backed by HM-Arch integration runtime handlers."""

    provider_id = MemoryProviderId.HM_ARCH

    def __init__(self, config: MemoryBackendRunConfig) -> None:
        super().__init__(config)
        self._integration = IntegrationConfig(
            db_path=str(self.storage_dir() / "benchmark.db"),
            recall_top_k=config.recall_top_k,
            max_context_chars=config.max_context_chars,
        )

    def _setup_provider(self) -> None:
        return None

    def _teardown_provider(self) -> None:
        return None

    @contextmanager
    def _runtime_env(self) -> Iterator[None]:
        db_path = self._integration.resolve_db_path()
        previous = os.environ.get("HM_ARCH_DB_PATH")
        os.environ["HM_ARCH_DB_PATH"] = db_path
        try:
            yield
        finally:
            if previous is None:
                os.environ.pop("HM_ARCH_DB_PATH", None)
            else:
                os.environ["HM_ARCH_DB_PATH"] = previous

    def ingest(self, turn: IngestTurn) -> IngestResult:
        self._require_ready()
        request = RecordRequest(
            user_message=turn.user_message,
            agent_message=turn.agent_message,
            session_id=self.config.namespace,
        )

        def _record() -> list[str]:
            with self._runtime_env():
                response = execute_record(request)
            if not response.ok:
                raise RuntimeError(response.error or "record failed")
            return list(response.memory_ids)

        try:
            memory_ids, latency_ms = measure_ms(_record)
        except Exception as exc:  # noqa: BLE001 — surface provider failures in metrics
            return IngestResult(
                ok=False,
                memory_ids=[],
                metrics=ProviderOperationMetrics(latency_ms=0.0),
                error=str(exc),
            )

        return IngestResult(
            ok=True,
            memory_ids=memory_ids,
            metrics=ProviderOperationMetrics(
                latency_ms=latency_ms,
                ingested_count=len(memory_ids),
            ),
        )

    def recall(self, query: str, *, top_k: int | None = None) -> RecallResult:
        self._require_ready()
        request = RecallRequest(
            task=query,
            top_k=top_k or self.config.recall_top_k,
            session_id=self.config.namespace,
        )

        def _recall() -> tuple[str, int]:
            with self._runtime_env():
                response = execute_recall(request)
            if not response.ok:
                raise RuntimeError(response.error or "recall failed")
            return response.context, response.result_count

        try:
            (context, hit_count), latency_ms = measure_ms(_recall)
        except Exception as exc:  # noqa: BLE001
            return RecallResult(
                ok=False,
                context="",
                metrics=ProviderOperationMetrics(latency_ms=0.0),
                error=str(exc),
            )

        return RecallResult(
            ok=True,
            context=context,
            metrics=ProviderOperationMetrics(
                latency_ms=latency_ms,
                context_chars=len(context),
                hit_count=hit_count,
            ),
        )

    def consolidate(self) -> ConsolidateResult:
        self._require_ready()
        request = ConsolidateRequest(session_id=self.config.namespace)

        def _consolidate() -> int:
            with self._runtime_env():
                response = execute_consolidate(request)
            if not response.ok:
                raise RuntimeError(response.error or "consolidate failed")
            return response.extracted_semantics

        try:
            extracted, latency_ms = measure_ms(_consolidate)
        except Exception as exc:  # noqa: BLE001
            return ConsolidateResult(
                ok=False,
                metrics=ProviderOperationMetrics(latency_ms=0.0),
                error=str(exc),
            )

        return ConsolidateResult(
            ok=True,
            metrics=ProviderOperationMetrics(latency_ms=latency_ms),
            extracted_semantics=extracted,
        )
