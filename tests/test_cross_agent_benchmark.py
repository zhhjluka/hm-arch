"""Offline tests for the cross-agent memory benchmark harness (HM-71 / MEM-68)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from benchmarks.cross_agent import (
    AgentKind,
    BenchmarkFamily,
    BenchmarkRunConfig,
    MemoryBackendKind,
    RunPhase,
    run_cross_agent_benchmark,
)
from benchmarks.cross_agent.agents.registry import create_agent_runner
from benchmarks.cross_agent.compatibility import UnsupportedCombinationError, assert_supported
from benchmarks.cross_agent.checkpoint import load_checkpoint
from benchmarks.cross_agent.fixtures.synthetic import all_synthetic_fixtures
from benchmarks.cross_agent.metrics import (
    approximate_token_count,
    exact_match_accuracy,
    hotpotqa_exact_match_accuracy,
    retrieval_hit_rate,
)
from benchmarks.cross_agent.protocol import AgentRunner, MemoryBackend
from benchmarks.cross_agent.run_id import derive_run_id, resolve_run_id
from benchmarks.cross_agent.runner import CrossAgentBenchmarkHarness, run_synthetic_matrix


@pytest.mark.parametrize("family", list(BenchmarkFamily))
def test_synthetic_fixture_lifecycle(tmp_path: Path, family: BenchmarkFamily) -> None:
    config = BenchmarkRunConfig(
        family=family,
        agent=AgentKind.CODEX,
        backend=MemoryBackendKind.HM_ARCH,
        seed=0,
        resume=False,
    )
    result = run_cross_agent_benchmark(config, output_root=tmp_path)

    expected_phases = {
        RunPhase.SETUP.value,
        RunPhase.INGEST.value,
        RunPhase.QUERY.value,
        RunPhase.EVALUATE.value,
        RunPhase.TEARDOWN.value,
        RunPhase.CHECKPOINT.value,
    }
    if family in {BenchmarkFamily.LOCOMO, BenchmarkFamily.HOTPOTQA}:
        expected_phases.add(RunPhase.CONSOLIDATE.value)

    assert expected_phases.issubset(set(result.phases_completed))
    assert result.aggregates.query_count == len(result.queries)
    assert result.aggregates.total_failure_count == 0

    run_dir = tmp_path / result.run_id
    assert (run_dir / "summary.json").is_file()
    assert (run_dir / "queries.csv").is_file()
    assert (run_dir / "queries.jsonl").is_file()
    assert (run_dir / "storage" / "checkpoint.json").is_file()


def test_deterministic_run_id() -> None:
    rid_a = derive_run_id(
        family=BenchmarkFamily.LOCOMO,
        agent=AgentKind.CODEX,
        backend=MemoryBackendKind.HM_ARCH,
        seed=0,
        top_k=5,
    )
    rid_b = derive_run_id(
        family=BenchmarkFamily.LOCOMO,
        agent=AgentKind.CODEX,
        backend=MemoryBackendKind.HM_ARCH,
        seed=0,
        top_k=5,
    )
    rid_c = derive_run_id(
        family=BenchmarkFamily.LOCOMO,
        agent=AgentKind.CODEX,
        backend=MemoryBackendKind.HM_ARCH,
        seed=1,
        top_k=5,
    )
    rid_d = derive_run_id(
        family=BenchmarkFamily.HOTPOTQA,
        agent=AgentKind.CODEX,
        backend=MemoryBackendKind.HM_ARCH,
        seed=0,
        top_k=20,
    )
    rid_e = derive_run_id(
        family=BenchmarkFamily.HOTPOTQA,
        agent=AgentKind.CODEX,
        backend=MemoryBackendKind.HM_ARCH,
        seed=0,
        top_k=5,
    )
    assert rid_a == rid_b
    assert rid_a != rid_c
    assert rid_d != rid_e


def test_top_k_run_isolation(tmp_path: Path) -> None:
    config_k5 = BenchmarkRunConfig(
        family=BenchmarkFamily.HOTPOTQA,
        agent=AgentKind.CODEX,
        backend=MemoryBackendKind.HM_ARCH,
        seed=0,
        top_k=5,
        resume=False,
    )
    config_k20 = BenchmarkRunConfig(
        family=BenchmarkFamily.HOTPOTQA,
        agent=AgentKind.CODEX,
        backend=MemoryBackendKind.HM_ARCH,
        seed=0,
        top_k=20,
        resume=False,
    )
    assert config_k5.run_id is None
    result_k5 = run_cross_agent_benchmark(config_k5, output_root=tmp_path)
    result_k20 = run_cross_agent_benchmark(config_k20, output_root=tmp_path)
    assert result_k5.run_id != result_k20.run_id
    assert (tmp_path / result_k5.run_id).is_dir()
    assert (tmp_path / result_k20.run_id).is_dir()


def test_non_resume_rerun_replaces_jsonl(tmp_path: Path) -> None:
    config = BenchmarkRunConfig(
        family=BenchmarkFamily.LOCOMO,
        agent=AgentKind.CODEX,
        backend=MemoryBackendKind.HM_ARCH,
        seed=0,
        resume=False,
    )
    first = run_cross_agent_benchmark(config, output_root=tmp_path)
    jsonl_path = tmp_path / first.run_id / "queries.jsonl"
    first_lines = jsonl_path.read_text(encoding="utf-8").strip().splitlines()
    assert len(first_lines) == len(first.queries)

    second = run_cross_agent_benchmark(config, output_root=tmp_path)
    second_lines = jsonl_path.read_text(encoding="utf-8").strip().splitlines()
    assert len(second_lines) == len(second.queries)
    assert len(second_lines) == len(first_lines)


def test_interrupted_checkpoint_reopens_backend(tmp_path: Path) -> None:
    from benchmarks.cross_agent.types import IngestItem, RecallOutcome

    class TrackingBackend:
        kind = "tracking"

        def __init__(self) -> None:
            self.open_count = 0
            self.close_count = 0
            self._ingested = False

        def open(self, storage_dir: Path, config: BenchmarkRunConfig) -> None:
            self.open_count += 1
            storage_dir.mkdir(parents=True, exist_ok=True)

        def close(self) -> None:
            self.close_count += 1

        def ingest(self, item: IngestItem) -> None:
            self._ingested = True

        def consolidate(self) -> None:
            return None

        def recall(self, query, *, top_k: int) -> RecallOutcome:
            return RecallOutcome(context="ok", retrieved_ids=(), recall_time_ms=1.0)

    class FailingAgent:
        kind = "failing"

        def __init__(self) -> None:
            self.calls = 0

        def open(self) -> None:
            return None

        def close(self) -> None:
            return None

        def reset_session(self) -> None:
            return None

        def answer(self, query, *, recalled_context: str, seed: int):
            from benchmarks.cross_agent.types import AgentOutcome

            self.calls += 1
            if self.calls == 1:
                raise RuntimeError("simulated agent crash")
            return AgentOutcome(
                answer="recovered",
                task_success=None,
                input_tokens=1,
                output_tokens=1,
                agent_time_ms=1.0,
            )

    config = BenchmarkRunConfig(
        family=BenchmarkFamily.TAU2_BENCH,
        agent=AgentKind.CODEX,
        backend=MemoryBackendKind.HM_ARCH,
        seed=0,
        resume=True,
    )
    backend = TrackingBackend()
    agent = FailingAgent()
    harness = CrossAgentBenchmarkHarness(output_root=tmp_path, backend=backend, agent=agent)

    partial = harness.run(config)
    assert backend.open_count == 1
    assert backend.close_count == 1
    assert len(partial.queries) == 2
    assert partial.queries[0].failure_count == 1
    assert partial.queries[1].failure_count == 0

    resumed = harness.run(config)
    assert backend.open_count == 2
    assert backend.close_count == 2
    assert len(resumed.queries) == 2


def test_teardown_after_ingest_exception(tmp_path: Path) -> None:
    from benchmarks.cross_agent.types import IngestItem

    class ExplodingBackend:
        kind = "exploding"

        def __init__(self) -> None:
            self.open_count = 0
            self.close_count = 0

        def open(self, storage_dir: Path, config: BenchmarkRunConfig) -> None:
            self.open_count += 1
            storage_dir.mkdir(parents=True, exist_ok=True)

        def close(self) -> None:
            self.close_count += 1

        def ingest(self, item: IngestItem) -> None:
            raise RuntimeError("ingest failed")

        def consolidate(self) -> None:
            return None

        def recall(self, query, *, top_k: int):
            raise AssertionError("recall should not run")

    config = BenchmarkRunConfig(
        family=BenchmarkFamily.LOCOMO,
        agent=AgentKind.CODEX,
        backend=MemoryBackendKind.HM_ARCH,
        seed=0,
        resume=False,
    )
    backend = ExplodingBackend()
    harness = CrossAgentBenchmarkHarness(output_root=tmp_path, backend=backend)

    with pytest.raises(RuntimeError, match="ingest failed"):
        harness.run(config)

    assert backend.open_count == 1
    assert backend.close_count == 1
    checkpoint = load_checkpoint(tmp_path / resolve_run_id(config) / "storage")
    assert checkpoint is not None
    assert checkpoint["status"] == "failed"
    assert checkpoint["error"] == "ingest failed"


def test_recall_exception_counts_as_query_failure(tmp_path: Path) -> None:
    from benchmarks.cross_agent.types import IngestItem

    class RecallExplodingBackend:
        kind = "recall_exploding"

        def open(self, storage_dir: Path, config: BenchmarkRunConfig) -> None:
            storage_dir.mkdir(parents=True, exist_ok=True)

        def close(self) -> None:
            return None

        def ingest(self, item: IngestItem) -> None:
            return None

        def consolidate(self) -> None:
            return None

        def recall(self, query, *, top_k: int):
            raise RuntimeError("recall failed")

    config = BenchmarkRunConfig(
        family=BenchmarkFamily.LOCOMO,
        agent=AgentKind.CODEX,
        backend=MemoryBackendKind.HM_ARCH,
        seed=0,
        resume=False,
    )
    harness = CrossAgentBenchmarkHarness(
        output_root=tmp_path,
        backend=RecallExplodingBackend(),
    )
    result = harness.run(config)
    assert all(q.failure_count >= 1 for q in result.queries)
    assert result.aggregates.total_failure_count >= len(result.queries)


def test_hm_arch_retrieval_beats_no_memory_baseline(tmp_path: Path) -> None:
    config = BenchmarkRunConfig(
        family=BenchmarkFamily.LOCOMO,
        agent=AgentKind.CODEX,
        backend=MemoryBackendKind.HM_ARCH,
        seed=0,
        resume=False,
    )
    hm_result = run_cross_agent_benchmark(config, output_root=tmp_path / "hm")

    no_mem_config = BenchmarkRunConfig(
        family=BenchmarkFamily.LOCOMO,
        agent=AgentKind.CODEX,
        backend=MemoryBackendKind.NO_MEMORY,
        seed=0,
        resume=False,
    )
    baseline = run_cross_agent_benchmark(no_mem_config, output_root=tmp_path / "none")

    hm_hits = [q.retrieval_hit_rate for q in hm_result.queries if q.retrieval_hit_rate is not None]
    base_hits = [q.retrieval_hit_rate for q in baseline.queries if q.retrieval_hit_rate is not None]
    assert hm_hits
    assert base_hits
    assert sum(hm_hits) / len(hm_hits) > sum(base_hits) / len(base_hits)


def test_checkpoint_resume_skips_completed_queries(tmp_path: Path) -> None:
    config = BenchmarkRunConfig(
        family=BenchmarkFamily.TAU2_BENCH,
        agent=AgentKind.HERMES,
        backend=MemoryBackendKind.HM_ARCH,
        seed=0,
        resume=True,
    )
    harness = CrossAgentBenchmarkHarness(output_root=tmp_path)
    first = harness.run(config)
    storage = Path(first.storage_dir)
    checkpoint = load_checkpoint(storage)
    assert checkpoint is not None
    assert checkpoint["completed_query_ids"]

    second = harness.run(config)
    assert second.run_id == first.run_id
    assert len(second.queries) == len(first.queries)


def test_unsupported_backend_agent_pairs_raise() -> None:
    with pytest.raises(UnsupportedCombinationError):
        assert_supported(MemoryBackendKind.MEM0, AgentKind.CODEX)


def test_all_agents_use_synthetic_runner() -> None:
    for kind in AgentKind:
        runner = create_agent_runner(kind)
        assert isinstance(runner, AgentRunner)
        assert runner.kind == "mock-synthetic"


def test_metric_helpers() -> None:
    assert exact_match_accuracy("Seattle", "  seattle ") == 1.0
    assert exact_match_accuracy("Seattle", "Boston") == 0.0
    assert hotpotqa_exact_match_accuracy("Norway", "Norway.") == 1.0
    assert hotpotqa_exact_match_accuracy("The Hague", "Hague") == 1.0
    assert hotpotqa_exact_match_accuracy("Norway", "Sweden") == 0.0
    assert retrieval_hit_rate(("a", "b"), ("a", "c")) == 0.5
    assert approximate_token_count("one two\nthree") == 3


def test_result_schema_covers_all_families(tmp_path: Path) -> None:
    results = run_synthetic_matrix(output_root=tmp_path)
    families = {r.config.family for r in results}
    assert families == set(BenchmarkFamily)

    for fixture in all_synthetic_fixtures():
        assert fixture.ingest_items
        assert fixture.queries

    summary = json.loads((tmp_path / results[0].run_id / "summary.json").read_text())
    assert "aggregates" in summary
    assert "queries" in summary
