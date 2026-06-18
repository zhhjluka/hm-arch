"""Mem0 memory backend — requires the real mem0ai SDK."""

from __future__ import annotations

import importlib.metadata
import json
from typing import Any, Protocol, runtime_checkable

from ..types import (
    BenchmarkQuery,
    IngestItem,
    IngestOutcome,
    OperationOutcome,
    ProviderDescriptor,
    ProviderUnavailableError,
    RecallOutcome,
)
from .base import BaseMemoryBackend


@runtime_checkable
class Mem0ClientProtocol(Protocol):
    """Minimal Mem0 surface required by the benchmark adapter."""

    def add(self, messages: list[dict[str, str]], **kwargs: Any) -> dict[str, Any]: ...

    def search(self, query: str, **kwargs: Any) -> dict[str, Any]: ...

    def delete_all(self, **kwargs: Any) -> None: ...


def _require_mem0_client(storage_dir, namespace: str) -> Mem0ClientProtocol:
    try:
        from mem0 import Memory  # type: ignore import-not-found]
    except ImportError as exc:
        raise ProviderUnavailableError(
            "Mem0 backend requires the mem0ai package. "
            "Install with `pip install mem0ai` or select the explicit `mock` backend "
            "for offline contract tests."
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


def _format_mem0_context(results: list[dict[str, Any]]) -> str:
    if not results:
        return ""
    lines = ["## Mem0 recalled memory", ""]
    for index, item in enumerate(results, start=1):
        lines.append(
            f"{index}. {item.get('memory', '')} (score={item.get('score', 0):.2f})"
        )
    return "\n".join(lines)


def _mem0_version() -> str | None:
    try:
        return importlib.metadata.version("mem0ai")
    except importlib.metadata.PackageNotFoundError:
        return None


class Mem0Backend(BaseMemoryBackend):
    """Benchmark adapter for Mem0 — never substitutes an offline fallback."""

    kind = "mem0"

    def __init__(self, *, client: Mem0ClientProtocol | None = None) -> None:
        super().__init__()
        self._client: Mem0ClientProtocol | None = client
        self._injected_client = client is not None

    def _setup_provider(self) -> None:
        if self._client is None:
            self._client = _require_mem0_client(self.storage_dir(), self._namespace())

    def _teardown_provider(self) -> OperationOutcome:
        if self._client is not None:
            self._client.delete_all(user_id=self._namespace())
        self._client = None
        return OperationOutcome()

    def _ingest_item(self, item: IngestItem) -> IngestOutcome:
        client = self._require_client()
        messages = [{"role": "user", "content": item.content}]
        payload = client.add(messages, user_id=self._namespace())
        results = payload.get("results", [])
        ingested_ids = tuple(str(entry.get("id", "")) for entry in results if entry.get("id"))
        return IngestOutcome(ingested_ids=ingested_ids)

    def _consolidate_provider(self) -> OperationOutcome:
        return OperationOutcome()

    def _reset_provider(self) -> OperationOutcome:
        client = self._require_client()
        client.delete_all(user_id=self._namespace())
        return OperationOutcome()

    def _recall_query(self, query: BenchmarkQuery, *, top_k: int) -> RecallOutcome:
        client = self._require_client()
        try:
            payload = client.search(query.question, user_id=self._namespace(), top_k=top_k)
        except TypeError:
            payload = client.search(
                query.question,
                filters={"user_id": self._namespace()},
                top_k=top_k,
            )
        results = payload.get("results", [])
        context = _format_mem0_context(results)
        return RecallOutcome(
            context=context,
            retrieved_ids=tuple(str(item.get("id", "")) for item in results if item.get("id")),
            recall_time_ms=0.0,
            hit_count=len(results),
        )

    def _provider_descriptor(self) -> ProviderDescriptor:
        return ProviderDescriptor(
            provider_id="mem0",
            version=_mem0_version(),
            config={
                "namespace": self._namespace(),
                "injected_client": self._injected_client,
            },
            simulated=False,
        )

    def _require_client(self) -> Mem0ClientProtocol:
        if self._client is None:
            raise RuntimeError("Mem0Backend.open() was not called")
        return self._client
