"""Contract tests for cross-agent memory benchmark backends (HM-72 / MEM-73)."""

from __future__ import annotations

from pathlib import Path

import pytest

from benchmarks.cross_agent.agents.registry import is_supported_coordinate
from benchmarks.cross_agent.backends.mem0 import Mem0Backend, OfflineMem0Client
from benchmarks.cross_agent.backends.native_memory import NativeMemoryBackend
from benchmarks.cross_agent.backends.openviking import (
    OfflineOpenVikingClient,
    OpenVikingBackend,
)
from benchmarks.cross_agent.backends.registry import create_memory_backend
from benchmarks.cross_agent.compatibility import (
    UnsupportedCombinationError,
    assert_supported,
    supported_pairs,
    unsupported_pairs,
)
from benchmarks.cross_agent.fixtures.synthetic import locomo_fixture
from benchmarks.cross_agent.protocol import MemoryBackend
from benchmarks.cross_agent.runner import CrossAgentBenchmarkHarness
from benchmarks.cross_agent.types import (
    AgentKind,
    BenchmarkFamily,
    BenchmarkQuery,
    BenchmarkRunConfig,
    IngestItem,
    MemoryBackendKind,
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
        item_id="contract-1",
        content=(
            "Remember that the staging API base URL is https://staging.example.com. "
            "Got it, I will use the staging API base URL for integration tests."
        ),
        session_id="contract-suite",
        metadata={"fixture": "contract"},
    )


@pytest.mark.parametrize(
    ("backend", "agent"),
    supported_pairs(),
    ids=lambda value: value.value if hasattr(value, "value") else str(value),
)
def test_supported_matrix_cells_instantiate(
    backend: MemoryBackendKind,
    agent: AgentKind,
) -> None:
    instance = create_memory_backend(backend, agent=agent)
    assert isinstance(instance, MemoryBackend)
    assert instance.kind == backend.value


@pytest.mark.parametrize(
    ("backend", "agent", "reason"),
    unsupported_pairs(),
    ids=lambda value: value.value if hasattr(value, "value") else str(value),
)
def test_unsupported_matrix_cells_raise(
    backend: MemoryBackendKind,
    agent: AgentKind,
    reason: str,
) -> None:
    with pytest.raises(UnsupportedCombinationError, match=reason.split(".")[0]):
        create_memory_backend(backend, agent=agent)


@pytest.mark.parametrize("backend", list(MemoryBackendKind))
def test_backend_lifecycle_contract(
    tmp_path: Path,
    synthetic_item: IngestItem,
    backend: MemoryBackendKind,
) -> None:
    agent = AgentKind.HERMES if backend is MemoryBackendKind.MEM0 else AgentKind.OPENCLAW
    if backend is MemoryBackendKind.OPENVIKING:
        agent = AgentKind.OPENCLAW
    if backend in {
        MemoryBackendKind.NO_MEMORY,
        MemoryBackendKind.HM_ARCH,
    }:
        agent = AgentKind.CODEX
    if backend is MemoryBackendKind.NATIVE_MEMORY:
        agent = AgentKind.CODEX

    config = _config(tmp_path, backend, agent, seed=hash(backend.value) % 1000)
    kwargs: dict = {}
    namespace = f"life-{backend.value}"
    if backend is MemoryBackendKind.MEM0:
        kwargs["client"] = OfflineMem0Client(user_id=namespace)
        instance = Mem0Backend(**kwargs)
    elif backend is MemoryBackendKind.OPENVIKING:
        kwargs["client"] = OfflineOpenVikingClient(namespace=namespace)
        instance = OpenVikingBackend(**kwargs)
    elif backend is MemoryBackendKind.NATIVE_MEMORY:
        instance = NativeMemoryBackend()
    else:
        instance = create_memory_backend(backend, agent=agent)

    storage_dir = tmp_path / "storage" / backend.value
    query = BenchmarkQuery(
        query_id="q1",
        question="staging API base URL",
        expected_answer="https://staging.example.com",
        expected_memory_ids=(synthetic_item.item_id,),
    )

    instance.open(storage_dir, config)
    try:
        assert storage_dir.exists()
        instance.ingest(synthetic_item)
        instance.consolidate()

        recall = instance.recall(query, top_k=5)
        assert recall.recall_time_ms >= 0.0
        assert recall.context_chars == len(recall.context)
        if backend in {MemoryBackendKind.NO_MEMORY, MemoryBackendKind.NATIVE_MEMORY}:
            assert recall.context == ""
            assert recall.hit_count == 0
        else:
            assert recall.hit_count >= 1
            assert recall.context_chars > 0
    finally:
        instance.close()


def test_hm_arch_backend_uses_isolated_database(
    tmp_path: Path,
    synthetic_item: IngestItem,
) -> None:
    config = _config(tmp_path, MemoryBackendKind.HM_ARCH, AgentKind.CODEX)
    backend = create_memory_backend(MemoryBackendKind.HM_ARCH, agent=AgentKind.CODEX)
    storage_dir = tmp_path / "hm-arch-only"
    backend.open(storage_dir, config)
    try:
        backend.ingest(synthetic_item)
        recall = backend.recall(
            BenchmarkQuery(
                query_id="q1",
                question="staging API",
                expected_memory_ids=(synthetic_item.item_id,),
            ),
            top_k=5,
        )
        assert "staging" in recall.context.lower()
        assert recall.context_chars == len(recall.context)
        assert (storage_dir / "hm_arch.db").exists()
    finally:
        backend.close()


def test_native_memory_marks_agent_managed_without_bridge(tmp_path: Path) -> None:
    config = _config(tmp_path, MemoryBackendKind.NATIVE_MEMORY, AgentKind.HERMES)
    backend = NativeMemoryBackend()
    storage_dir = tmp_path / "native"
    backend.open(storage_dir, config)
    try:
        recall = backend.recall(
            BenchmarkQuery(query_id="q1", question="anything"),
            top_k=5,
        )
        assert recall.agent_managed is True
        assert recall.context == ""
    finally:
        backend.close()


class _RecordingNativeBridge:
    def ingest(self, item: IngestItem) -> tuple[str, ...]:
        return (f"native-{item.item_id}",)

    def recall(
        self, query: BenchmarkQuery, *, top_k: int
    ) -> tuple[str, tuple[str, ...], int]:
        context = f"native recall for {query.question}"
        return context, ("native-1",), 1

    def consolidate(self) -> None:
        return None


def test_native_memory_delegates_to_bridge(tmp_path: Path) -> None:
    config = _config(tmp_path, MemoryBackendKind.NATIVE_MEMORY, AgentKind.OPENCLAW)
    backend = NativeMemoryBackend(bridge=_RecordingNativeBridge())
    storage_dir = tmp_path / "bridge"
    backend.open(storage_dir, config)
    try:
        recall = backend.recall(
            BenchmarkQuery(query_id="q1", question="project conventions"),
            top_k=5,
        )
        assert recall.agent_managed is True
        assert recall.hit_count == 1
        assert "native recall" in recall.context
    finally:
        backend.close()


def test_mem0_and_openviking_offline_clients_are_isolated(
    tmp_path: Path,
    synthetic_item: IngestItem,
) -> None:
    mem0_a = Mem0Backend(client=OfflineMem0Client(user_id="mem0-a"))
    mem0_b = Mem0Backend(client=OfflineMem0Client(user_id="mem0-b"))
    config = _config(tmp_path, MemoryBackendKind.MEM0, AgentKind.HERMES)
    for backend, namespace in ((mem0_a, "mem0-a"), (mem0_b, "mem0-b")):
        backend.open(tmp_path / namespace, config)

    try:
        mem0_a.ingest(synthetic_item)
        query = BenchmarkQuery(query_id="q1", question="staging API")
        assert mem0_a.recall(query, top_k=5).hit_count == 1
        assert mem0_b.recall(query, top_k=5).hit_count == 0
    finally:
        mem0_a.close()
        mem0_b.close()

    ov_a = OpenVikingBackend(client=OfflineOpenVikingClient(namespace="ov-a"))
    ov_b = OpenVikingBackend(client=OfflineOpenVikingClient(namespace="ov-b"))
    for backend, namespace in ((ov_a, "ov-a"), (ov_b, "ov-b")):
        backend.open(tmp_path / namespace, config)

    try:
        ov_a.ingest(synthetic_item)
        query = BenchmarkQuery(query_id="q1", question="staging API")
        assert ov_a.recall(query, top_k=5).hit_count == 1
        assert ov_b.recall(query, top_k=5).hit_count == 0
    finally:
        ov_a.close()
        ov_b.close()


def test_assert_supported_does_not_substitute_unsupported_provider() -> None:
    with pytest.raises(UnsupportedCombinationError):
        assert_supported(MemoryBackendKind.MEM0, AgentKind.CODEX)


def test_native_memory_coordinate_is_unsupported_in_harness(tmp_path: Path) -> None:
    config = BenchmarkRunConfig(
        family=BenchmarkFamily.LOCOMO,
        agent=AgentKind.CODEX,
        backend=MemoryBackendKind.NATIVE_MEMORY,
        seed=0,
        resume=False,
        use_mock_agent=False,
    )
    supported, rationale = is_supported_coordinate(config)
    assert supported is False
    assert "bridge" in rationale.lower() or "native" in rationale.lower()

    result = CrossAgentBenchmarkHarness(output_root=tmp_path).run(config)
    assert result.agent_metadata.get("status") == "unsupported"
    assert result.queries == []


def test_mem0_backend_requires_package_when_no_client_injected(tmp_path: Path) -> None:
    from benchmarks.cross_agent.backends.errors import ProviderPackageRequired

    backend = Mem0Backend()
    config = _config(tmp_path, MemoryBackendKind.MEM0, AgentKind.HERMES)
    with pytest.raises(ProviderPackageRequired, match="mem0ai"):
        backend.open(tmp_path / "mem0-live", config)


def test_openviking_backend_requires_package_when_no_client_injected(tmp_path: Path) -> None:
    from benchmarks.cross_agent.backends.errors import ProviderPackageRequired

    backend = OpenVikingBackend()
    config = _config(tmp_path, MemoryBackendKind.OPENVIKING, AgentKind.OPENCLAW)
    with pytest.raises(ProviderPackageRequired, match="openviking"):
        backend.open(tmp_path / "ov-live", config)


def test_mem0_harness_run_with_injected_client(tmp_path: Path) -> None:
    namespace = "mem0-harness"
    backend = Mem0Backend(client=OfflineMem0Client(user_id=namespace))
    config = BenchmarkRunConfig(
        family=BenchmarkFamily.LOCOMO,
        agent=AgentKind.HERMES,
        backend=MemoryBackendKind.MEM0,
        seed=0,
        resume=False,
    )
    result = CrossAgentBenchmarkHarness(output_root=tmp_path, backend=backend).run(config)
    assert result.aggregates.total_failure_count == 0
    assert any(q.recall_hit_count > 0 for q in result.queries)


def test_openviking_harness_run_with_injected_client(tmp_path: Path) -> None:
    namespace = "ov-harness"
    backend = OpenVikingBackend(client=OfflineOpenVikingClient(namespace=namespace))
    config = BenchmarkRunConfig(
        family=BenchmarkFamily.LOCOMO,
        agent=AgentKind.OPENCLAW,
        backend=MemoryBackendKind.OPENVIKING,
        seed=0,
        resume=False,
    )
    result = CrossAgentBenchmarkHarness(output_root=tmp_path, backend=backend).run(config)
    assert result.aggregates.total_failure_count == 0
    assert any(q.recall_hit_count > 0 for q in result.queries)


def test_locomo_fixture_has_expected_queries() -> None:
    fixture = locomo_fixture()
    assert fixture.ingest_items
    assert fixture.queries
