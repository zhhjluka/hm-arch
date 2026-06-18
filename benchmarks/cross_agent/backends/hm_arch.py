"""HM-Arch memory backend adapter."""

from __future__ import annotations

import time
from pathlib import Path

from hm_arch import HMArch
from hm_arch.config import MemoryConfig
from hm_arch.integrations.common.recall import build_turn_start_context
from hm_arch.types import EventType

from ..protocol import MemoryBackend
from ..types import BenchmarkQuery, BenchmarkRunConfig, IngestItem, RecallOutcome


class HmArchBackend:
    """HM-Arch adapter with isolated per-run SQLite storage."""

    kind = "hm_arch"

    def __init__(self) -> None:
        self._memory: HMArch | None = None

    def open(self, storage_dir: Path, config: BenchmarkRunConfig) -> None:
        storage_dir.mkdir(parents=True, exist_ok=True)
        _ = config
        self._memory = HMArch(
            config=MemoryConfig(
                db_path=str(storage_dir / "hm_arch.db"),
                archive_root=str(storage_dir / "archives"),
                auto_consolidate=False,
            )
        )
        self._id_map: dict[str, str] = {}

    def close(self) -> None:
        if self._memory is not None:
            self._memory.close()
            self._memory = None

    def ingest(self, item: IngestItem) -> None:
        memory = self._require_memory()
        receipt = memory.add(
            item.content,
            event_type=EventType.CONVERSATION,
            importance=0.7,
            session=item.session_id,
        )
        self._id_map[item.item_id] = receipt.memory_id

    def consolidate(self) -> None:
        self._require_memory().consolidate()

    def recall(self, query: BenchmarkQuery, *, top_k: int) -> RecallOutcome:
        memory = self._require_memory()
        t0 = time.perf_counter()
        try:
            context = build_turn_start_context(
                memory,
                query.question,
                top_k=top_k,
            )
            hits = memory.search(query.question, top_k=top_k)
            retrieved_fixture_ids = tuple(
                fixture_id
                for fixture_id, memory_id in self._id_map.items()
                if any(hit.memory_id == memory_id for hit in hits.results)
            )
            elapsed = (time.perf_counter() - t0) * 1000.0
            return RecallOutcome(
                context=context,
                retrieved_ids=retrieved_fixture_ids,
                recall_time_ms=elapsed,
            )
        except Exception as exc:  # noqa: BLE001 — benchmark must count failures
            elapsed = (time.perf_counter() - t0) * 1000.0
            return RecallOutcome(
                context="",
                retrieved_ids=(),
                recall_time_ms=elapsed,
                failure_count=1,
                error=str(exc),
            )

    def _require_memory(self) -> HMArch:
        if self._memory is None:
            raise RuntimeError("HmArchBackend.open() was not called")
        return self._memory
