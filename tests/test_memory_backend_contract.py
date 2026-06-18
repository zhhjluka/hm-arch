"""Contract tests for cross-agent memory backends (MEM-73)."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest

from benchmarks.cross_agent.backends.mem0 import Mem0Backend
from benchmarks.cross_agent.backends.mock import MockMemoryBackend, MockMemoryStore
from benchmarks.cross_agent.backends.native import NativeMemoryBackend
from benchmarks.cross_agent.backends.openviking import OpenVikingBackend
from benchmarks.cross_agent.backends.registry import create_memory_backend
from benchmarks.cross_agent.compatibility import (
    assert_supported,
    supported_pairs,
    unsupported_pairs,
)
from benchmarks.cross_agent.protocol import AgentNativeMemoryBridge
from benchmarks.cross_agent.types import (
    AgentKind,
    BenchmarkFamily,
    BenchmarkQuery,
    BenchmarkRunConfig,
    IngestItem,
    IngestOutcome,
    MemoryBackendKind,
    OperationOutcome,
    ProviderUnavailableError,
    RecallOutcome,
    UnsupportedCombinationError,
)


def _config(
    tmp_path: Path,
    backend: MemoryBackendKind,
    agent: AgentKind = AgentKind.CODEX,
    *,
    seed: int = 0,
) -> BenchmarkRunConfig:
    return BenchmarkRunConfig(
        family=BenchmarkFamily.LOCOMO,
        agent=agent,
        backend=backend,
        seed=seed,
        resume=False,
    )


@pytest.fixture
def synthetic_item() -> IngestItem:
    return IngestItem(
        item_id="turn-1",
        content=(
            "Remember that the staging API base URL is https://staging.example.com. "
            "Got it, I will use the staging API base URL for integration tests."
        ),
        session_id="session-1",
    )


@pytest.mark.parametrize(
    ("backend", "agent"),
    supported_pairs(),
    ids=lambda value: value.value if hasattr(value, "value") else str(value),
)
def test_supported_matrix_cells_instantiate(
    tmp_path: Path,
    backend: MemoryBackendKind,
    agent: AgentKind,
) -> None:
    config = _config(tmp_path, backend, agent)
    if backend is MemoryBackendKind.NATIVE_MEMORY:
        instance = create_memory_backend(backend, config)
        with pytest.raises(UnsupportedCombinationError):
            instance.open(tmp_path / "storage", config)
        return
    if backend in {MemoryBackendKind.MEM0, MemoryBackendKind.OPENVIKING}:
        with pytest.raises(ProviderUnavailableError):
            backend_instance = create_memory_backend(backend, config)
            backend_instance.open(tmp_path / "storage", config)
        return
    instance = create_memory_backend(backend, config)
    assert instance.kind == backend.value


@pytest.mark.parametrize(
    ("backend", "agent", "reason"),
    unsupported_pairs(),
    ids=lambda value: value.value if hasattr(value, "value") else str(value),
)
def test_unsupported_matrix_cells_raise(
    tmp_path: Path,
    backend: MemoryBackendKind,
    agent: AgentKind,
    reason: str,
) -> None:
    with pytest.raises(UnsupportedCombinationError, match=reason.split(".")[0]):
        create_memory_backend(backend, _config(tmp_path, backend, agent))


@pytest.mark.parametrize("backend", [MemoryBackendKind.MOCK, MemoryBackendKind.NO_MEMORY, MemoryBackendKind.HM_ARCH])
def test_backend_lifecycle_contract(
    tmp_path: Path,
    synthetic_item: IngestItem,
    backend: MemoryBackendKind,
) -> None:
    config = _config(tmp_path, backend, AgentKind.CODEX)
    instance = create_memory_backend(backend, config)
    storage = tmp_path / "storage"
    query = BenchmarkQuery(
        query_id="q1",
        question="What is the staging API base URL?",
        expected_answer="https://staging.example.com",
        expected_memory_ids=("turn-1",),
    )

    instance.open(storage, config)
    try:
        ingest = instance.ingest(synthetic_item)
        assert ingest.failure_count == 0

        recall = instance.recall(query, top_k=5)
        assert recall.failure_count == 0
        assert recall.context_chars == len(recall.context)
        if backend is MemoryBackendKind.NO_MEMORY:
            assert recall.hit_count == 0
            assert recall.context == ""
        else:
            assert recall.hit_count >= 1
            assert recall.context_chars > 0

        consolidate = instance.consolidate()
        assert consolidate.failure_count == 0

        reset = instance.reset()
        assert reset.failure_count == 0
        empty = instance.recall(query, top_k=5)
        assert empty.hit_count == 0

        artifacts = instance.provider_artifacts()
        assert artifacts.provider.provider_id in {backend.value, "mock"}
        assert artifacts.provider.simulated is (backend is MemoryBackendKind.MOCK)
        operations = {record.operation for record in artifacts.operations}
        assert {"ingest", "recall", "consolidate", "reset"}.issubset(operations)
    finally:
        teardown = instance.close()
        assert teardown.failure_count == 0


def test_mem0_without_sdk_raises_provider_unavailable(tmp_path: Path) -> None:
    config = _config(tmp_path, MemoryBackendKind.MEM0, AgentKind.HERMES)
    backend = create_memory_backend(MemoryBackendKind.MEM0, config)
    with pytest.raises(ProviderUnavailableError, match="mem0ai"):
        backend.open(tmp_path / "mem0", config)


def test_openviking_without_sdk_raises_provider_unavailable(tmp_path: Path) -> None:
    config = _config(tmp_path, MemoryBackendKind.OPENVIKING, AgentKind.OPENCLAW)
    backend = create_memory_backend(MemoryBackendKind.OPENVIKING, config)
    with pytest.raises(ProviderUnavailableError, match="openviking"):
        backend.open(tmp_path / "ov", config)


def test_mock_backend_never_masquerades_as_mem0(tmp_path: Path) -> None:
    config = _config(tmp_path, MemoryBackendKind.MOCK, AgentKind.CODEX)
    backend = create_memory_backend(MemoryBackendKind.MOCK, config)
    backend.open(tmp_path / "mock", config)
    try:
        descriptor = backend.provider_artifacts().provider
        assert descriptor.provider_id == "mock"
        assert descriptor.simulated is True
        assert descriptor.provider_id != "mem0"
        assert descriptor.provider_id != "openviking"
    finally:
        backend.close()


@dataclass
class _RecordingNativeBridge:
    """Test double for agent-native memory delegation."""

    entries: list[IngestItem] = field(default_factory=list)

    def ingest(self, item: IngestItem) -> IngestOutcome:
        self.entries.append(item)
        return IngestOutcome(ingested_ids=(item.item_id,))

    def recall(self, query: BenchmarkQuery, *, top_k: int) -> RecallOutcome:
        _ = top_k
        context = f"native recall for {query.question}"
        return RecallOutcome(
            context=context,
            retrieved_ids=("native-1",),
            recall_time_ms=0.0,
            hit_count=1,
        )

    def consolidate(self) -> OperationOutcome:
        return OperationOutcome()


def test_native_memory_requires_agent_bridge(tmp_path: Path) -> None:
    config = _config(tmp_path, MemoryBackendKind.NATIVE_MEMORY, AgentKind.HERMES)
    backend = NativeMemoryBackend(bridge=None)
    with pytest.raises(UnsupportedCombinationError, match="native-memory bridge"):
        backend.open(tmp_path / "native", config)


def test_native_memory_delegates_to_bridge(
    tmp_path: Path,
    synthetic_item: IngestItem,
) -> None:
    bridge = _RecordingNativeBridge()
    config = _config(tmp_path, MemoryBackendKind.NATIVE_MEMORY, AgentKind.OPENCLAW)
    backend = NativeMemoryBackend(bridge=bridge)
    query = BenchmarkQuery(query_id="q1", question="project conventions")

    backend.open(tmp_path / "native", config)
    try:
        backend.ingest(synthetic_item)
        recall = backend.recall(query, top_k=3)
        assert recall.hit_count == 1
        assert "native recall" in recall.context
        descriptor = backend.provider_artifacts().provider
        assert descriptor.provider_id == "native_memory"
        assert descriptor.simulated is False
    finally:
        backend.close()


@dataclass
class _FakeMem0Client:
    user_id: str
    _memories: list[dict[str, Any]] = field(default_factory=list)

    def add(self, messages: list[dict[str, str]], **kwargs: Any) -> dict[str, Any]:
        text = " ".join(message["content"] for message in messages)
        memory_id = f"mem0-{len(self._memories) + 1}"
        entry = {"id": memory_id, "memory": text}
        self._memories.append(entry)
        return {"results": [entry]}

    def search(self, query: str, **kwargs: Any) -> dict[str, Any]:
        query_tokens = {token for token in query.lower().split() if token}
        scored = [
            {**entry, "score": 1.0}
            for entry in self._memories
            if any(token in entry["memory"].lower() for token in query_tokens)
        ]
        return {"results": scored[: int(kwargs.get("top_k", 10))]}

    def delete_all(self, **kwargs: Any) -> None:
        self._memories.clear()


def test_mem0_and_mock_stores_are_isolated(
    tmp_path: Path,
    synthetic_item: IngestItem,
) -> None:
    query = BenchmarkQuery(query_id="q1", question="staging API")

    mem0_a = Mem0Backend(client=_FakeMem0Client(user_id="a"))
    mem0_b = Mem0Backend(client=_FakeMem0Client(user_id="b"))
    config_a = _config(tmp_path, MemoryBackendKind.MEM0, AgentKind.HERMES, seed=1)
    config_b = _config(tmp_path, MemoryBackendKind.MEM0, AgentKind.HERMES, seed=2)

    for backend, config, subdir in (
        (mem0_a, config_a, "mem0-a"),
        (mem0_b, config_b, "mem0-b"),
    ):
        backend.open(tmp_path / subdir, config)
    try:
        mem0_a.ingest(synthetic_item)
        assert mem0_a.recall(query, top_k=5).hit_count == 1
        assert mem0_b.recall(query, top_k=5).hit_count == 0
    finally:
        mem0_a.close()
        mem0_b.close()

    mock_a = MockMemoryBackend(store=MockMemoryStore(namespace="a"))
    mock_b = MockMemoryBackend(store=MockMemoryStore(namespace="b"))
    mock_config_a = _config(tmp_path, MemoryBackendKind.MOCK, AgentKind.CODEX, seed=3)
    mock_config_b = _config(tmp_path, MemoryBackendKind.MOCK, AgentKind.CODEX, seed=4)
    mock_a.open(tmp_path / "mock-a", mock_config_a)
    mock_b.open(tmp_path / "mock-b", mock_config_b)
    try:
        mock_a.ingest(synthetic_item)
        assert mock_a.recall(query, top_k=5).hit_count == 1
        assert mock_b.recall(query, top_k=5).hit_count == 0
    finally:
        mock_a.close()
        mock_b.close()


def test_assert_supported_does_not_substitute_unsupported_provider() -> None:
    with pytest.raises(UnsupportedCombinationError):
        assert_supported(MemoryBackendKind.MEM0, AgentKind.CODEX)
