"""Offline and optional-package OpenViking benchmark backend."""

from __future__ import annotations

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
class OpenVikingClientProtocol(Protocol):
    """Minimal OpenViking surface required by the benchmark adapter."""

    def initialize(self) -> None:
        """Prepare local or remote storage."""

    def add_resource(self, path: str, **kwargs: Any) -> dict[str, Any]:
        """Ingest a text resource into the OpenViking store."""

    def find(self, query: str, **kwargs: Any) -> list[dict[str, Any]]:
        """Semantic search over stored resources."""

    def close(self) -> None:
        """Release client resources."""


@dataclass
class OfflineOpenVikingClient:
    """Deterministic in-process OpenViking substitute for offline tests."""

    namespace: str
    _resources: list[dict[str, Any]] = field(default_factory=list)

    def initialize(self) -> None:
        return None

    def add_resource(self, path: str, **kwargs: Any) -> dict[str, Any]:
        content = Path(path).read_text(encoding="utf-8")
        entry = {
            "uri": f"viking://session/{self.namespace}/{len(self._resources) + 1}",
            "content": content,
        }
        self._resources.append(entry)
        return {"status": "ok", "uri": entry["uri"]}

    def find(self, query: str, **kwargs: Any) -> list[dict[str, Any]]:
        query_tokens = {token for token in query.lower().split() if token}
        hits: list[dict[str, Any]] = []
        for entry in self._resources:
            content = str(entry["content"]).lower()
            overlap = sum(1 for token in query_tokens if token in content)
            if overlap:
                hits.append(
                    {
                        "uri": entry["uri"],
                        "content": entry["content"],
                        "score": overlap / max(len(query_tokens), 1),
                    }
                )
        hits.sort(key=lambda item: item["score"], reverse=True)
        limit = int(kwargs.get("limit", kwargs.get("top_k", 10)))
        return hits[:limit]

    def close(self) -> None:
        self._resources.clear()


def _format_openviking_context(hits: list[dict[str, Any]]) -> str:
    if not hits:
        return ""
    lines = ["## OpenViking recalled context", ""]
    for index, item in enumerate(hits, start=1):
        lines.append(
            f"{index}. [{item.get('uri', 'viking://unknown')}] "
            f"{item.get('content', '')} (score={item.get('score', 0):.2f})"
        )
    return "\n".join(lines)


def create_openviking_client(storage_dir: Path, namespace: str) -> OpenVikingClientProtocol:
    """Create an OpenViking client, preferring the real SDK when installed."""
    try:
        import openviking as ov  # type: ignore import-not-found
    except ImportError:
        return OfflineOpenVikingClient(namespace=namespace)

    client = ov.SyncOpenViking(path=str(storage_dir / "openviking"))
    client.initialize()
    return client


class OpenVikingMemoryBackend(BaseMemoryBackend):
    """Benchmark adapter for OpenViking with offline fallback storage."""

    provider_id = MemoryProviderId.OPENVIKING

    def __init__(self, config, *, client: OpenVikingClientProtocol | None = None) -> None:
        super().__init__(config)
        self._client: OpenVikingClientProtocol | None = client
        self._turn_counter = 0

    def _setup_provider(self) -> None:
        if self._client is None:
            self._client = create_openviking_client(self.storage_dir(), self.config.namespace)
        self._client.initialize()
        self._turn_counter = 0

    def _teardown_provider(self) -> None:
        if self._client is not None:
            self._client.close()
        self._client = None

    def _write_turn_file(self, turn: IngestTurn) -> Path:
        self._turn_counter += 1
        turn_path = self.storage_dir() / f"turn-{self._turn_counter:04d}.md"
        lines = []
        if turn.user_message.strip():
            lines.append(f"User: {turn.user_message}")
        if turn.agent_message.strip():
            lines.append(f"Assistant: {turn.agent_message}")
        turn_path.write_text("\n".join(lines), encoding="utf-8")
        return turn_path

    def ingest(self, turn: IngestTurn) -> IngestResult:
        self._require_ready()
        assert self._client is not None

        def _add() -> list[str]:
            turn_path = self._write_turn_file(turn)
            payload = self._client.add_resource(str(turn_path))
            uri = str(payload.get("uri", turn_path.name))
            return [uri]

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

        def _find() -> tuple[str, int]:
            hits = self._client.find(query, limit=effective_top_k)  # type: ignore[union-attr]
            context = _format_openviking_context(hits)
            return context, len(hits)

        try:
            (context, hit_count), latency_ms = measure_ms(_find)
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
        assert self._client is not None

        def _commit() -> int:
            commit = getattr(self._client, "commit_session", None)
            if callable(commit):
                commit()
            return 0

        try:
            extracted, latency_ms = measure_ms(_commit)
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
