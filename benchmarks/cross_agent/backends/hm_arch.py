"""HM-Arch memory backend adapter."""

from __future__ import annotations

from hm_arch import HMArch
from hm_arch.config import MemoryConfig
from hm_arch.integrations.common.recall import build_turn_start_context
from hm_arch.types import EventType

from ..types import (
    BenchmarkQuery,
    IngestItem,
    IngestOutcome,
    OperationOutcome,
    ProviderDescriptor,
    RecallOutcome,
)
from .base import BaseMemoryBackend


class HmArchBackend(BaseMemoryBackend):
    """HM-Arch adapter with isolated per-run SQLite storage."""

    kind = "hm_arch"

    def __init__(self) -> None:
        super().__init__()
        self._memory: HMArch | None = None
        self._id_map: dict[str, str] = {}

    def _setup_provider(self) -> None:
        self._memory = HMArch(
            config=MemoryConfig(
                db_path=str(self.storage_dir() / "hm_arch.db"),
                archive_root=str(self.storage_dir() / "archives"),
                auto_consolidate=False,
            )
        )
        self._id_map = {}

    def _teardown_provider(self) -> OperationOutcome:
        if self._memory is not None:
            self._memory.close()
            self._memory = None
        return OperationOutcome()

    def _ingest_item(self, item: IngestItem) -> IngestOutcome:
        memory = self._require_memory()
        receipt = memory.add(
            item.content,
            event_type=EventType.CONVERSATION,
            importance=0.7,
            session=item.session_id,
        )
        self._id_map[item.item_id] = receipt.memory_id
        return IngestOutcome(ingested_ids=(item.item_id,))

    def _consolidate_provider(self) -> OperationOutcome:
        self._require_memory().consolidate()
        return OperationOutcome()

    def _reset_provider(self) -> OperationOutcome:
        self._teardown_provider()
        self._setup_provider()
        return OperationOutcome()

    def _recall_query(self, query: BenchmarkQuery, *, top_k: int) -> RecallOutcome:
        memory = self._require_memory()
        context = build_turn_start_context(memory, query.question, top_k=top_k)
        hits = memory.search(query.question, top_k=top_k)
        retrieved_fixture_ids = tuple(
            fixture_id
            for fixture_id, memory_id in self._id_map.items()
            if any(hit.memory_id == memory_id for hit in hits.results)
        )
        return RecallOutcome(
            context=context,
            retrieved_ids=retrieved_fixture_ids,
            recall_time_ms=0.0,
            hit_count=len(retrieved_fixture_ids),
        )

    def _provider_descriptor(self) -> ProviderDescriptor:
        db_path = str(self._storage_dir / "hm_arch.db") if self._storage_dir else "hm_arch.db"
        namespace = self._namespace() if self._config is not None else "unknown"
        return ProviderDescriptor(
            provider_id="hm_arch",
            version=None,
            config={
                "db_path": db_path,
                "namespace": namespace,
            },
        )

    def _require_memory(self) -> HMArch:
        if self._memory is None:
            raise RuntimeError("HmArchBackend.open() was not called")
        return self._memory
