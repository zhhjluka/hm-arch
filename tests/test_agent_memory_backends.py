"""Contract tests for cross-agent memory benchmark backends (MEM-73)."""

from __future__ import annotations

from pathlib import Path

import pytest

from benchmarks.agent_memory import (
    AgentId,
    IngestTurn,
    MemoryBackendRunConfig,
    MemoryProviderId,
    OfflineMem0Client,
    OfflineOpenVikingClient,
    UnsupportedCombinationError,
    assert_supported,
    create_memory_backend,
    supported_pairs,
    unsupported_pairs,
)
from benchmarks.agent_memory.backends.mem0 import Mem0MemoryBackend
from benchmarks.agent_memory.backends.native import NativeMemoryBackend
from benchmarks.agent_memory.backends.openviking import OpenVikingMemoryBackend
from benchmarks.agent_memory.contract import (
    ConsolidateResult,
    IngestResult,
    RecallResult,
)


def _config(
    tmp_path: Path,
    provider_id: MemoryProviderId,
    agent_id: AgentId = AgentId.CODEX,
    *,
    namespace: str = "contract-suite",
) -> MemoryBackendRunConfig:
    return MemoryBackendRunConfig(
        run_id="run-001",
        namespace=namespace,
        workspace_root=tmp_path,
        agent_id=agent_id,
        provider_id=provider_id,
    )


@pytest.fixture
def synthetic_turn() -> IngestTurn:
    return IngestTurn(
        user_message="Remember that the staging API base URL is https://staging.example.com",
        agent_message="Got it, I will use the staging API base URL for integration tests.",
        metadata={"fixture": "contract"},
    )


@pytest.mark.parametrize(
    ("provider_id", "agent_id"),
    supported_pairs(),
    ids=lambda value: value.value if hasattr(value, "value") else str(value),
)
def test_supported_matrix_cells_instantiate(
    tmp_path: Path,
    provider_id: MemoryProviderId,
    agent_id: AgentId,
) -> None:
    backend = create_memory_backend(_config(tmp_path, provider_id, agent_id))
    assert backend.provider_id is provider_id
    assert backend.agent_id is agent_id


@pytest.mark.parametrize(
    ("provider_id", "agent_id", "reason"),
    unsupported_pairs(),
    ids=lambda value: value.value if hasattr(value, "value") else str(value),
)
def test_unsupported_matrix_cells_raise(
    tmp_path: Path,
    provider_id: MemoryProviderId,
    agent_id: AgentId,
    reason: str,
) -> None:
    with pytest.raises(UnsupportedCombinationError, match=reason.split(".")[0]):
        create_memory_backend(_config(tmp_path, provider_id, agent_id))


@pytest.mark.parametrize("provider_id", list(MemoryProviderId))
def test_backend_lifecycle_contract(
    tmp_path: Path,
    synthetic_turn: IngestTurn,
    provider_id: MemoryProviderId,
) -> None:
    agent_id = AgentId.HERMES if provider_id is MemoryProviderId.MEM0 else AgentId.OPENCLAW
    if provider_id is MemoryProviderId.OPENVIKING:
        agent_id = AgentId.OPENCLAW
    if provider_id in {MemoryProviderId.NO_MEMORY, MemoryProviderId.HM_ARCH, MemoryProviderId.NATIVE_MEMORY}:
        agent_id = AgentId.CODEX

    config = _config(tmp_path, provider_id, agent_id, namespace=f"life-{provider_id.value}")
    kwargs: dict = {}
    if provider_id is MemoryProviderId.MEM0:
        kwargs["client"] = OfflineMem0Client(user_id=config.namespace)
    if provider_id is MemoryProviderId.OPENVIKING:
        kwargs["client"] = OfflineOpenVikingClient(namespace=config.namespace)

    backend = create_memory_backend(config, **kwargs)
    storage_dir = config.storage_dir()

    backend.setup()
    assert storage_dir.exists()

    ingest = backend.ingest(synthetic_turn)
    assert isinstance(ingest, IngestResult)
    assert ingest.ok is True
    assert ingest.metrics.latency_ms >= 0.0

    recall = backend.recall("staging API base URL")
    assert isinstance(recall, RecallResult)
    assert recall.ok is True
    assert recall.metrics.latency_ms >= 0.0
    assert recall.metrics.context_chars == len(recall.context)
    if provider_id in {MemoryProviderId.NO_MEMORY, MemoryProviderId.NATIVE_MEMORY}:
        assert recall.context == ""
        assert recall.metrics.hit_count == 0
    else:
        assert recall.metrics.hit_count >= 1
        assert recall.metrics.context_chars > 0

    consolidate = backend.consolidate()
    assert isinstance(consolidate, ConsolidateResult)
    assert consolidate.ok is True
    assert consolidate.metrics.latency_ms >= 0.0

    backend.reset()
    assert storage_dir.exists()
    empty_recall = backend.recall("staging API base URL")
    assert empty_recall.ok is True
    assert empty_recall.metrics.hit_count == 0

    backend.teardown()
    assert not storage_dir.exists()


def test_hm_arch_backend_uses_isolated_database(tmp_path: Path, synthetic_turn: IngestTurn) -> None:
    config = _config(tmp_path, MemoryProviderId.HM_ARCH, AgentId.CODEX, namespace="hm-arch-only")
    backend = create_memory_backend(config)
    backend.setup()
    try:
        ingest = backend.ingest(synthetic_turn)
        assert ingest.ok is True
        assert ingest.metrics.ingested_count >= 1

        recall = backend.recall("staging API")
        assert recall.ok is True
        assert "staging" in recall.context.lower()
        assert recall.metrics.context_chars == len(recall.context)
        assert (config.storage_dir() / "benchmark.db").exists()
    finally:
        backend.teardown()


def test_native_memory_marks_agent_managed_without_bridge(tmp_path: Path) -> None:
    backend = create_memory_backend(
        _config(tmp_path, MemoryProviderId.NATIVE_MEMORY, AgentId.HERMES, namespace="native")
    )
    backend.setup()
    try:
        recall = backend.recall("anything")
        assert recall.agent_managed is True
        assert recall.context == ""
    finally:
        backend.teardown()


class _RecordingNativeBridge:
    def ingest(self, turn: IngestTurn) -> IngestResult:
        from benchmarks.agent_memory.contract import ProviderOperationMetrics

        return IngestResult(
            ok=True,
            memory_ids=["native-1"],
            metrics=ProviderOperationMetrics(
                latency_ms=1.0,
                ingested_count=1,
            ),
        )

    def recall(self, query: str, *, top_k: int | None = None) -> RecallResult:
        from benchmarks.agent_memory.contract import ProviderOperationMetrics

        context = f"native recall for {query}"
        return RecallResult(
            ok=True,
            context=context,
            metrics=ProviderOperationMetrics(
                latency_ms=2.0,
                context_chars=len(context),
                hit_count=1,
            ),
        )

    def consolidate(self) -> ConsolidateResult:
        from benchmarks.agent_memory.contract import ProviderOperationMetrics

        return ConsolidateResult(
            ok=True,
            metrics=ProviderOperationMetrics(latency_ms=0.5),
            extracted_semantics=0,
        )


def test_native_memory_delegates_to_bridge(tmp_path: Path) -> None:
    config = _config(tmp_path, MemoryProviderId.NATIVE_MEMORY, AgentId.OPENCLAW, namespace="bridge")
    backend = NativeMemoryBackend(config, bridge=_RecordingNativeBridge())
    backend.setup()
    try:
        recall = backend.recall("project conventions")
        assert recall.agent_managed is True
        assert recall.metrics.hit_count == 1
        assert "native recall" in recall.context
    finally:
        backend.teardown()


def test_mem0_and_openviking_offline_clients_are_isolated(tmp_path: Path, synthetic_turn: IngestTurn) -> None:
    mem0_a = Mem0MemoryBackend(
        _config(tmp_path, MemoryProviderId.MEM0, AgentId.HERMES, namespace="mem0-a"),
        client=OfflineMem0Client(user_id="mem0-a"),
    )
    mem0_b = Mem0MemoryBackend(
        _config(tmp_path, MemoryProviderId.MEM0, AgentId.HERMES, namespace="mem0-b"),
        client=OfflineMem0Client(user_id="mem0-b"),
    )
    for backend in (mem0_a, mem0_b):
        backend.setup()
    try:
        mem0_a.ingest(synthetic_turn)
        assert mem0_a.recall("staging API").metrics.hit_count == 1
        assert mem0_b.recall("staging API").metrics.hit_count == 0
    finally:
        mem0_a.teardown()
        mem0_b.teardown()

    ov_a = OpenVikingMemoryBackend(
        _config(tmp_path, MemoryProviderId.OPENVIKING, AgentId.OPENCLAW, namespace="ov-a"),
        client=OfflineOpenVikingClient(namespace="ov-a"),
    )
    ov_b = OpenVikingMemoryBackend(
        _config(tmp_path, MemoryProviderId.OPENVIKING, AgentId.OPENCLAW, namespace="ov-b"),
        client=OfflineOpenVikingClient(namespace="ov-b"),
    )
    for backend in (ov_a, ov_b):
        backend.setup()
    try:
        ov_a.ingest(synthetic_turn)
        assert ov_a.recall("staging API").metrics.hit_count == 1
        assert ov_b.recall("staging API").metrics.hit_count == 0
    finally:
        ov_a.teardown()
        ov_b.teardown()


def test_assert_supported_does_not_substitute_unsupported_provider() -> None:
    with pytest.raises(UnsupportedCombinationError):
        assert_supported(MemoryProviderId.MEM0, AgentId.CODEX)
