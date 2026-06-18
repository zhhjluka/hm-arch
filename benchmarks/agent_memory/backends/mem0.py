"""Offline and optional-package Mem0 benchmark backend."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

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
class Mem0ClientProtocol(Protocol):
    """Minimal Mem0 surface required by the benchmark adapter."""

    def add(self, messages: list[dict[str, str]], **kwargs: Any) -> dict[str, Any]:
        """Store a conversation turn."""

    def search(self, query: str, **kwargs: Any) -> dict[str, Any]:
        """Search scoped memories for *query*."""

    def delete_all(self, **kwargs: Any) -> None:
        """Remove all memories for the active namespace."""


@dataclass
class OfflineMem0Client:
    """Deterministic in-process Mem0 substitute for offline contract tests."""

    user_id: str
    _memories: list[dict[str, Any]] = field(default_factory=list)

    def add(self, messages: list[dict[str, str]], **kwargs: Any) -> dict[str, Any]:
        text = " ".join(message["content"] for message in messages if message.get("content"))
        memory_id = f"mem0-{len(self._memories) + 1}"
        entry = {
            "id": memory_id,
            "memory": text,
            "user_id": self.user_id,
        }
        self._memories.append(entry)
        return {"results": [entry]}

    def search(self, query: str, **kwargs: Any) -> dict[str, Any]:
        query_tokens = {token for token in query.lower().split() if token}
        scored: list[dict[str, Any]] = []
        for entry in self._memories:
            memory_text = str(entry["memory"]).lower()
            overlap = sum(1 for token in query_tokens if token in memory_text)
            if overlap:
                scored.append({**entry, "score": overlap / max(len(query_tokens), 1)})
        scored.sort(key=lambda item: item["score"], reverse=True)
        top_k = int(kwargs.get("top_k", 10))
        return {"results": scored[:top_k]}

    def delete_all(self, **kwargs: Any) -> None:
        self._memories.clear()


def _format_mem0_context(results: list[dict[str, Any]]) -> str:
    if not results:
        return ""
    lines = ["## Mem0 recalled memory", ""]
    for index, item in enumerate(results, start=1):
        lines.append(f"{index}. {item.get('memory', '')} (score={item.get('score', 0):.2f})")
    return "\n".join(lines)


def create_mem0_client(storage_dir: Path, namespace: str) -> Mem0ClientProtocol:
    """Create a Mem0 client, preferring the real SDK when installed."""
    user_id = namespace
    config_path = storage_dir / "mem0_config.json"
    try:
        from mem0 import Memory  # type: ignore import-not-found
    except ImportError:
        return OfflineMem0Client(user_id=user_id)

    config = {
        "vector_store": {
            "provider": "qdrant",
            "config": {
                "collection_name": f"hm_arch_bench_{namespace}",
                "path": str(storage_dir / "qdrant"),
            },
        },
    }
    config_path.write_text(json.dumps(config), encoding="utf-8")
    return Memory.from_config(config_dict=config)


class Mem0MemoryBackend(BaseMemoryBackend):
    """Benchmark adapter for Mem0 with offline fallback storage."""

    provider_id = MemoryProviderId.MEM0

    def __init__(self, config, *, client: Mem0ClientProtocol | None = None) -> None:
        super().__init__(config)
        self._client: Mem0ClientProtocol | None = client

    def _setup_provider(self) -> None:
        if self._client is None:
            self._client = create_mem0_client(self.storage_dir(), self.config.namespace)

    def _teardown_provider(self) -> None:
        if self._client is not None:
            self._client.delete_all(user_id=self.config.namespace)
        self._client = None

    def ingest(self, turn: IngestTurn) -> IngestResult:
        self._require_ready()
        assert self._client is not None
        messages = []
        if turn.user_message.strip():
            messages.append({"role": "user", "content": turn.user_message})
        if turn.agent_message.strip():
            messages.append({"role": "assistant", "content": turn.agent_message})

        def _add() -> list[str]:
            payload = self._client.add(  # type: ignore[union-attr]
                messages,
                user_id=self.config.namespace,
            )
            results = payload.get("results", [])
            return [str(item.get("id", "")) for item in results if item.get("id")]

        try:
            memory_ids, latency_ms = measure_ms(_add)
        except Exception as exc:  # noqa: BLE001
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
        assert self._client is not None
        effective_top_k = top_k or self.config.recall_top_k

        def _search() -> tuple[str, int]:
            payload = self._client.search(  # type: ignore[union-attr]
                query,
                user_id=self.config.namespace,
                top_k=effective_top_k,
            )
            results = payload.get("results", [])
            context = _format_mem0_context(results)
            return context, len(results)

        try:
            (context, hit_count), latency_ms = measure_ms(_search)
        except TypeError:
            # OSS Mem0 builds may expect filters={"user_id": ...} instead.
            def _search_with_filters() -> tuple[str, int]:
                payload = self._client.search(  # type: ignore[union-attr]
                    query,
                    filters={"user_id": self.config.namespace},
                    top_k=effective_top_k,
                )
                results = payload.get("results", [])
                context = _format_mem0_context(results)
                return context, len(results)

            try:
                (context, hit_count), latency_ms = measure_ms(_search_with_filters)
            except Exception as exc:  # noqa: BLE001
                return RecallResult(
                    ok=False,
                    context="",
                    metrics=ProviderOperationMetrics(latency_ms=0.0),
                    error=str(exc),
                )
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

        def _noop() -> int:
            return 0

        extracted, latency_ms = measure_ms(_noop)
        return ConsolidateResult(
            ok=True,
            metrics=ProviderOperationMetrics(latency_ms=latency_ms),
            extracted_semantics=extracted,
        )
