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
from benchmarks.cross_agent.backends.registry import create_memory_backend
from benchmarks.cross_agent.checkpoint import load_checkpoint
from benchmarks.cross_agent.fixtures.synthetic import all_synthetic_fixtures
from benchmarks.cross_agent.metrics import (
    approximate_token_count,
    exact_match_accuracy,
    retrieval_hit_rate,
)
from benchmarks.cross_agent.protocol import AgentRunner, MemoryBackend
from benchmarks.cross_agent.run_id import derive_run_id
from benchmarks.cross_agent.runner import CrossAgentBenchmarkHarness, run_synthetic_matrix


@pytest.mark.parametrize("family", list(BenchmarkFamily))
def test_synthetic_fixture_lifecycle(tmp_path: Path, family: BenchmarkFamily) -> None:
    config = BenchmarkRunConfig(
        family=family,
        agent=AgentKind.CODEX,
        backend=MemoryBackendKind.HM_ARCH,
        seed=0,
        resume=False,
        use_mock_agent=True,
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
    assert (run_dir / "agent_workspace" / "storage" / "checkpoint.json").is_file()


def test_deterministic_run_id() -> None:
    rid_a = derive_run_id(
        family=BenchmarkFamily.LOCOMO,
        agent=AgentKind.CODEX,
        backend=MemoryBackendKind.HM_ARCH,
        seed=0,
    )
    rid_b = derive_run_id(
        family=BenchmarkFamily.LOCOMO,
        agent=AgentKind.CODEX,
        backend=MemoryBackendKind.HM_ARCH,
        seed=0,
    )
    rid_c = derive_run_id(
        family=BenchmarkFamily.LOCOMO,
        agent=AgentKind.CODEX,
        backend=MemoryBackendKind.HM_ARCH,
        seed=1,
    )
    assert rid_a == rid_b
    assert rid_a != rid_c


def test_hm_arch_retrieval_beats_no_memory_baseline(tmp_path: Path) -> None:
    config = BenchmarkRunConfig(
        family=BenchmarkFamily.LOCOMO,
        agent=AgentKind.CODEX,
        backend=MemoryBackendKind.HM_ARCH,
        seed=0,
        resume=False,
        use_mock_agent=True,
    )
    hm_result = run_cross_agent_benchmark(config, output_root=tmp_path / "hm")

    no_mem_config = BenchmarkRunConfig(
        family=BenchmarkFamily.LOCOMO,
        agent=AgentKind.CODEX,
        backend=MemoryBackendKind.NO_MEMORY,
        seed=0,
        resume=False,
        use_mock_agent=True,
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
        use_mock_agent=True,
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


def test_stub_backends_raise_until_registered() -> None:
    for kind in (
        MemoryBackendKind.NATIVE_MEMORY,
        MemoryBackendKind.OPENVIKING,
        MemoryBackendKind.MEM0,
    ):
        backend = create_memory_backend(kind)
        with pytest.raises(NotImplementedError):
            backend.open(Path("/tmp/unused"), BenchmarkRunConfig(
                family=BenchmarkFamily.LOCOMO,
                agent=AgentKind.CODEX,
                backend=kind,
            ))


def test_all_agents_use_mock_runner_by_default() -> None:
    from benchmarks.cross_agent.agents.synthetic import MockSyntheticAgentRunner

    for kind in AgentKind:
        runner = create_agent_runner(kind)
        assert isinstance(runner, AgentRunner)
        assert isinstance(runner, MockSyntheticAgentRunner)


def test_metric_helpers() -> None:
    assert exact_match_accuracy("Seattle", "  seattle ") == 1.0
    assert exact_match_accuracy("Seattle", "Boston") == 0.0
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
