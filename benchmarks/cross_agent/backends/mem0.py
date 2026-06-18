"""Mem0 memory backend adapter for cross-agent benchmarks."""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

from ..types import BenchmarkQuery, BenchmarkRunConfig, IngestItem, RecallOutcome
from .errors import ProviderPackageRequired


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
    """Create a Mem0 client from the installed SDK.

    Raises :class:`ProviderPackageRequired` when ``mem0ai`` is not installed.
  Tests may inject :class:`OfflineMem0Client` directly instead of calling this.
    """
    try:
        from mem0 import Memory  # type: ignore import-not-found
    except ImportError as exc:
        raise ProviderPackageRequired(
            "Mem0 backend requires the mem0ai package. "
            "Install with: pip install mem0ai"
        ) from exc

    config = {
        "vector_store": {
            "provider": "qdrant",
            "config": {
                "collection_name": f"hm_arch_bench_{namespace}",
                "path": str(storage_dir / "qdrant"),
            },
        },
    }
    config_path = storage_dir / "mem0_config.json"
    config_path.write_text(json.dumps(config), encoding="utf-8")
    return Memory.from_config(config_dict=config)


class Mem0Backend:
    """Benchmark adapter for Mem0."""

    kind = "mem0"

    def __init__(self, *, client: Mem0ClientProtocol | None = None) -> None:
        self._client: Mem0ClientProtocol | None = client
        self._namespace = ""
        self._storage_dir = Path()
        self._id_map: dict[str, str] = {}

    def open(self, storage_dir: Path, config: BenchmarkRunConfig) -> None:
        storage_dir.mkdir(parents=True, exist_ok=True)
        self._storage_dir = storage_dir
        self._namespace = f"{config.family.value}-{config.seed}"
        self._id_map = {}
        if self._client is None:
            self._client = create_mem0_client(storage_dir, self._namespace)

    def close(self) -> None:
        if self._client is not None:
            self._client.delete_all(user_id=self._namespace)
        self._client = None

    def ingest(self, item: IngestItem) -> None:
        client = self._require_client()
        messages = [{"role": "user", "content": item.content}]
        payload = client.add(messages, user_id=self._namespace)
        for result in payload.get("results", []):
            memory_id = str(result.get("id", ""))
            if memory_id:
                self._id_map[item.item_id] = memory_id

    def consolidate(self) -> None:
        return None

    def recall(self, query: BenchmarkQuery, *, top_k: int) -> RecallOutcome:
        client = self._require_client()
        t0 = time.perf_counter()
        try:
            try:
                payload = client.search(query.question, user_id=self._namespace, top_k=top_k)
            except TypeError:
                payload = client.search(
                    query.question,
                    filters={"user_id": self._namespace},
                    top_k=top_k,
                )
            results = payload.get("results", [])
            context = _format_mem0_context(results)
            retrieved_fixture_ids = tuple(
                fixture_id
                for fixture_id, memory_id in self._id_map.items()
                if any(str(item.get("id")) == memory_id for item in results)
            )
            elapsed = (time.perf_counter() - t0) * 1000.0
            return RecallOutcome(
                context=context,
                retrieved_ids=retrieved_fixture_ids,
                recall_time_ms=elapsed,
                context_chars=len(context),
                hit_count=len(results),
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

    def _require_client(self) -> Mem0ClientProtocol:
        if self._client is None:
            raise RuntimeError("Mem0Backend.open() was not called")
        return self._client
