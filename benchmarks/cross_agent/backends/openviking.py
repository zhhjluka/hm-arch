"""OpenViking memory backend adapter for cross-agent benchmarks."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

from ..types import BenchmarkQuery, BenchmarkRunConfig, IngestItem, RecallOutcome
from .errors import ProviderPackageRequired


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
    """Deterministic in-process OpenViking substitute for offline contract tests."""

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
    """Create an OpenViking client from the installed SDK.

    Raises :class:`ProviderPackageRequired` when ``openviking`` is not installed.
  Tests may inject :class:`OfflineOpenVikingClient` directly instead of calling this.
    """
    try:
        import openviking as ov  # type: ignore import-not-found
    except ImportError as exc:
        raise ProviderPackageRequired(
            "OpenViking backend requires the openviking package. "
            "Install with: pip install openviking"
        ) from exc

    client = ov.SyncOpenViking(path=str(storage_dir / "openviking"))
    client.initialize()
    return client


class OpenVikingBackend:
    """Benchmark adapter for OpenViking."""

    kind = "openviking"

    def __init__(self, *, client: OpenVikingClientProtocol | None = None) -> None:
        self._client: OpenVikingClientProtocol | None = client
        self._storage_dir = Path()
        self._namespace = ""
        self._turn_counter = 0
        self._id_map: dict[str, str] = {}

    def open(self, storage_dir: Path, config: BenchmarkRunConfig) -> None:
        storage_dir.mkdir(parents=True, exist_ok=True)
        self._storage_dir = storage_dir
        self._namespace = f"{config.family.value}-{config.seed}"
        self._turn_counter = 0
        self._id_map = {}
        if self._client is None:
            self._client = create_openviking_client(storage_dir, self._namespace)
        self._client.initialize()

    def close(self) -> None:
        if self._client is not None:
            self._client.close()
        self._client = None

    def ingest(self, item: IngestItem) -> None:
        client = self._require_client()
        self._turn_counter += 1
        turn_path = self._storage_dir / f"turn-{self._turn_counter:04d}.md"
        turn_path.write_text(item.content, encoding="utf-8")
        payload = client.add_resource(str(turn_path))
        uri = str(payload.get("uri", turn_path.name))
        self._id_map[item.item_id] = uri

    def consolidate(self) -> None:
        client = self._require_client()
        commit = getattr(client, "commit_session", None)
        if callable(commit):
            commit()

    def recall(self, query: BenchmarkQuery, *, top_k: int) -> RecallOutcome:
        client = self._require_client()
        t0 = time.perf_counter()
        try:
            hits = client.find(query.question, limit=top_k)
            context = _format_openviking_context(hits)
            hit_uris = {str(item.get("uri")) for item in hits}
            retrieved_fixture_ids = tuple(
                fixture_id
                for fixture_id, uri in self._id_map.items()
                if uri in hit_uris
            )
            elapsed = (time.perf_counter() - t0) * 1000.0
            return RecallOutcome(
                context=context,
                retrieved_ids=retrieved_fixture_ids,
                recall_time_ms=elapsed,
                context_chars=len(context),
                hit_count=len(hits),
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

    def _require_client(self) -> OpenVikingClientProtocol:
        if self._client is None:
            raise RuntimeError("OpenVikingBackend.open() was not called")
        return self._client
