"""Explicit mock backend for offline contract tests — never labeled as a real provider."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ..types import (
    BenchmarkQuery,
    IngestItem,
    IngestOutcome,
    OperationOutcome,
    ProviderDescriptor,
    RecallOutcome,
)
from .base import BaseMemoryBackend


@dataclass
class MockMemoryStore:
    """Deterministic in-process memory for contract tests."""

    namespace: str
    _entries: list[dict[str, Any]] = field(default_factory=list)

    def add(self, content: str) -> str:
        entry_id = f"mock-{len(self._entries) + 1}"
        self._entries.append({"id": entry_id, "content": content})
        return entry_id

    def search(self, query: str, *, top_k: int) -> list[dict[str, Any]]:
        query_tokens = {token for token in query.lower().split() if token}
        scored: list[dict[str, Any]] = []
        for entry in self._entries:
            content = str(entry["content"]).lower()
            overlap = sum(1 for token in query_tokens if token in content)
            if overlap:
                scored.append(
                    {
                        **entry,
                        "score": overlap / max(len(query_tokens), 1),
                    }
                )
        scored.sort(key=lambda item: item["score"], reverse=True)
        return scored[:top_k]

    def clear(self) -> None:
        self._entries.clear()


def _format_mock_context(results: list[dict[str, Any]]) -> str:
    if not results:
        return ""
    lines = ["## Mock recalled memory", ""]
    for index, item in enumerate(results, start=1):
        lines.append(
            f"{index}. {item.get('content', '')} (score={item.get('score', 0):.2f})"
        )
    return "\n".join(lines)


class MockMemoryBackend(BaseMemoryBackend):
    """Offline substitute selected explicitly — artifacts always mark simulated=True."""

    kind = "mock"

    def __init__(self, *, store: MockMemoryStore | None = None) -> None:
        super().__init__()
        self._store: MockMemoryStore | None = store

    def _setup_provider(self) -> None:
        if self._store is None:
            self._store = MockMemoryStore(namespace=self._namespace())

    def _teardown_provider(self) -> OperationOutcome:
        if self._store is not None:
            self._store.clear()
        self._store = None
        return OperationOutcome()

    def _ingest_item(self, item: IngestItem) -> IngestOutcome:
        store = self._require_store()
        entry_id = store.add(item.content)
        return IngestOutcome(ingested_ids=(entry_id,))

    def _consolidate_provider(self) -> OperationOutcome:
        return OperationOutcome()

    def _reset_provider(self) -> OperationOutcome:
        self._require_store().clear()
        return OperationOutcome()

    def _recall_query(self, query: BenchmarkQuery, *, top_k: int) -> RecallOutcome:
        store = self._require_store()
        hits = store.search(query.question, top_k=top_k)
        context = _format_mock_context(hits)
        return RecallOutcome(
            context=context,
            retrieved_ids=tuple(str(item["id"]) for item in hits),
            recall_time_ms=0.0,
            hit_count=len(hits),
        )

    def _provider_descriptor(self) -> ProviderDescriptor:
        return ProviderDescriptor(
            provider_id="mock",
            version="offline-contract",
            config={"namespace": self._namespace()},
            simulated=True,
        )

    def _require_store(self) -> MockMemoryStore:
        if self._store is None:
            raise RuntimeError("MockMemoryBackend.open() was not called")
        return self._store
