"""OpenViking memory backend — requires the real openviking SDK."""

from __future__ import annotations

import importlib.metadata
from pathlib import Path
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
class OpenVikingClientProtocol(Protocol):
    """Minimal OpenViking surface required by the benchmark adapter."""

    def initialize(self) -> None: ...

    def add_resource(self, path: str, **kwargs: Any) -> dict[str, Any]: ...

    def find(self, query: str, **kwargs: Any) -> list[dict[str, Any]]: ...

    def close(self) -> None: ...


def _require_openviking_client(storage_dir: Path) -> OpenVikingClientProtocol:
    try:
        import openviking as ov  # type: ignore import-not-found]
    except ImportError as exc:
        raise ProviderUnavailableError(
            "OpenViking backend requires the openviking package. "
            "Install with `pip install openviking` or select the explicit `mock` backend "
            "for offline contract tests."
        ) from exc

    client = ov.SyncOpenViking(path=str(storage_dir / "openviking"))
    client.initialize()
    return client


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


def _openviking_version() -> str | None:
    try:
        return importlib.metadata.version("openviking")
    except importlib.metadata.PackageNotFoundError:
        return None


class OpenVikingBackend(BaseMemoryBackend):
    """Benchmark adapter for OpenViking — never substitutes an offline fallback."""

    kind = "openviking"

    def __init__(self, *, client: OpenVikingClientProtocol | None = None) -> None:
        super().__init__()
        self._client: OpenVikingClientProtocol | None = client
        self._injected_client = client is not None
        self._turn_counter = 0

    def _setup_provider(self) -> None:
        if self._client is None:
            self._client = _require_openviking_client(self.storage_dir())
        else:
            self._client.initialize()
        self._turn_counter = 0

    def _teardown_provider(self) -> OperationOutcome:
        if self._client is not None:
            self._client.close()
        self._client = None
        return OperationOutcome()

    def _write_turn_file(self, item: IngestItem) -> Path:
        self._turn_counter += 1
        turn_path = self.storage_dir() / f"turn-{self._turn_counter:04d}.md"
        turn_path.write_text(item.content, encoding="utf-8")
        return turn_path

    def _ingest_item(self, item: IngestItem) -> IngestOutcome:
        client = self._require_client()
        turn_path = self._write_turn_file(item)
        payload = client.add_resource(str(turn_path))
        uri = str(payload.get("uri", turn_path.name))
        return IngestOutcome(ingested_ids=(uri,))

    def _consolidate_provider(self) -> OperationOutcome:
        client = self._require_client()
        commit = getattr(client, "commit_session", None)
        if callable(commit):
            commit()
        return OperationOutcome()

    def _reset_provider(self) -> OperationOutcome:
        self._teardown_provider()
        self._setup_provider()
        return OperationOutcome()

    def _recall_query(self, query: BenchmarkQuery, *, top_k: int) -> RecallOutcome:
        client = self._require_client()
        hits = client.find(query.question, limit=top_k)
        return RecallOutcome(
            context=_format_openviking_context(hits),
            retrieved_ids=tuple(str(item.get("uri", "")) for item in hits if item.get("uri")),
            recall_time_ms=0.0,
            hit_count=len(hits),
        )

    def _provider_descriptor(self) -> ProviderDescriptor:
        return ProviderDescriptor(
            provider_id="openviking",
            version=_openviking_version(),
            config={
                "namespace": self._namespace(),
                "injected_client": self._injected_client,
            },
            simulated=False,
        )

    def _require_client(self) -> OpenVikingClientProtocol:
        if self._client is None:
            raise RuntimeError("OpenVikingBackend.open() was not called")
        return self._client
