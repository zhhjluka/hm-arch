"""Tests for HotpotQA matrix execution (MEM-77)."""

from __future__ import annotations

import json
import stat
import sys
from pathlib import Path

import pytest

from benchmarks.cross_agent.fixtures.hotpotqa import (
    HOTPOTQA_SUBSET_VERSION,
    compute_subset_hash,
    get_hotpotqa_fixture,
    load_hotpotqa_config,
)
from benchmarks.cross_agent.fixtures.synthetic import get_synthetic_fixture, hotpotqa_fixture
from benchmarks.cross_agent.hotpotqa import (
    CellStatus,
    expected_runnable_cell_count,
    iter_hotpotqa_matrix_cells,
    run_hotpotqa_matrix,
    runnable_non_openclaw_cells,
)
from benchmarks.cross_agent.hotpotqa.manifest import resolve_comparison_executable
from benchmarks.cross_agent.hotpotqa.summary import HotpotqaCellSummary, build_matrix_summary
from benchmarks.cross_agent.types import AgentKind, BenchmarkFamily, MemoryBackendKind

REPO_ROOT = Path(__file__).resolve().parents[1]
FAKE_CLI = REPO_ROOT / "tests" / "fixtures" / "fake_agent_cli.py"


def _write_fake_executable(path: Path) -> str:
    script = f"""#!/bin/sh
exec {sys.executable} {FAKE_CLI} "$@"
"""
    path.write_text(script, encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IEXEC)
    return str(path)


def test_hotpotqa_fixture_uses_versioned_subset() -> None:
    fixture = hotpotqa_fixture()
    versioned = get_hotpotqa_fixture()
    assert fixture == versioned
    assert len(fixture.queries) == 5
    assert len(fixture.ingest_items) == 12


def test_hotpotqa_subset_hash_is_stable() -> None:
    assert len(compute_subset_hash()) == 64
    assert compute_subset_hash() == compute_subset_hash()


def test_get_synthetic_fixture_hotpotqa_matches_versioned_subset() -> None:
    assert get_synthetic_fixture(BenchmarkFamily.HOTPOTQA) == get_hotpotqa_fixture()


def test_matrix_cell_counts() -> None:
    cells = iter_hotpotqa_matrix_cells()
    assert len(cells) == len(MemoryBackendKind) * len(AgentKind) * 2
    assert expected_runnable_cell_count() == 16
    runnable = runnable_non_openclaw_cells()
    assert len(runnable) == 12
    assert all(cell.agent is not AgentKind.OPENCLAW for cell in runnable)
    assert all(cell.status is CellStatus.RUN for cell in runnable)


def test_openclaw_real_cells_are_runnable() -> None:
    openclaw_run = [
        cell
        for cell in iter_hotpotqa_matrix_cells()
        if cell.agent is AgentKind.OPENCLAW
        and cell.backend in {MemoryBackendKind.NO_MEMORY, MemoryBackendKind.HM_ARCH}
    ]
    assert len(openclaw_run) == 4
    assert all(cell.status is CellStatus.RUN for cell in openclaw_run)


def test_run_hotpotqa_matrix_mock_smoke_writes_artifacts(tmp_path: Path) -> None:
    summary = run_hotpotqa_matrix(
        output_root=tmp_path,
        seed=0,
        use_mock_agent=True,
        execution_mode="mock_smoke",
        command="pytest mock-smoke",
    )
    summary_path = tmp_path / "matrix_summary.json"
    manifest_path = tmp_path / "run_manifest.json"
    assert summary_path.is_file()
    assert manifest_path.is_file()
    loaded = json.loads(summary_path.read_text(encoding="utf-8"))
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert loaded["subset_version"] == HOTPOTQA_SUBSET_VERSION
    assert loaded["subset_hash"] == compute_subset_hash()
    assert loaded["execution_mode"] == "mock_smoke"
    assert loaded["use_mock_agent"] is True
    assert loaded["executed_cells"] == 0
    assert loaded["mock_smoke_cells"] == 16
    assert loaded.get("test_double_cells", 0) == 0
    assert loaded["pending_cells"] == 0
    assert loaded["unsupported_cells"] == 24
    assert len(loaded["cells"]) == 40
    assert manifest["execution_mode"] == "mock_smoke"

    mock_rows = [row for row in loaded["cells"] if row["run_id"]]
    assert len(mock_rows) == 16
    for row in mock_rows:
        assert row["use_mock_agent"] is True
        assert row["runner_implementation"] == "mock-synthetic"
        run_dir = tmp_path / row["run_id"]
        assert (run_dir / "summary.json").is_file()
        assert (run_dir / "queries.jsonl").is_file()
        assert (run_dir / "retrieval_evidence.jsonl").is_file()

    pending_dirs = list((tmp_path / "pending").glob("*/status.json"))
    assert len(pending_dirs) == 0

    config = load_hotpotqa_config()
    assert summary["answer_prompt_template"] == config["answer_prompt_template"]


def test_run_hotpotqa_matrix_real_cli_writes_provenance(tmp_path: Path) -> None:
    fake_executable = _write_fake_executable(tmp_path / "fake-agent-cli")
    summary = run_hotpotqa_matrix(
        output_root=tmp_path,
        seed=0,
        use_mock_agent=False,
        agent_executable=fake_executable,
        allow_test_double=True,
        execution_mode="comparison",
        command="pytest comparison",
    )
    loaded = json.loads((tmp_path / "matrix_summary.json").read_text(encoding="utf-8"))
    assert loaded["execution_mode"] == "comparison"
    assert loaded["use_mock_agent"] is False
    assert loaded["executed_cells"] == 0
    assert loaded["test_double_cells"] == 16
    assert loaded["mock_smoke_cells"] == 0
    assert loaded["agent_executables"] is not None

    test_double_rows = [
        row for row in loaded["cells"] if row["run_id"] and row["executable_source"] == "fake_double"
    ]
    assert len(test_double_rows) == 16
    for row in test_double_rows:
        assert row["use_mock_agent"] is False
        assert row["runner_implementation"] != "mock-synthetic"
        assert row["executable_source"] == "fake_double"
        summary_path = tmp_path / row["run_id"] / "summary.json"
        run_summary = json.loads(summary_path.read_text(encoding="utf-8"))
        assert run_summary["config"]["use_mock_agent"] is False

    hm_arch_k5 = next(
        row
        for row in test_double_rows
        if row["backend"] == "hm_arch" and row["top_k"] == 5 and row["agent"] == "codex"
    )
    assert hm_arch_k5["mean_accuracy"] is not None
    assert hm_arch_k5["mean_retrieval_hit_rate"] is None

    no_memory = next(row for row in test_double_rows if row["backend"] == "no_memory")
    assert no_memory["mean_retrieval_hit_rate"] == 0.0

    tradeoffs = loaded["tradeoffs"]
    assert any("not agent conclusions" in item for item in tradeoffs)


def test_run_hotpotqa_matrix_comparison_without_cli_marks_pending(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("PATH", "")
    summary = run_hotpotqa_matrix(
        output_root=tmp_path,
        seed=0,
        use_mock_agent=False,
        execution_mode="comparison",
        command="pytest comparison-pending",
    )
    loaded = json.loads((tmp_path / "matrix_summary.json").read_text(encoding="utf-8"))
    manifest = json.loads((tmp_path / "run_manifest.json").read_text(encoding="utf-8"))
    assert loaded["executed_cells"] == 0
    assert loaded["test_double_cells"] == 0
    assert loaded["pending_cells"] == 16
    assert sorted(manifest.get("agent_cli_unavailable") or []) == [
        "claude_code",
        "codex",
        "hermes",
        "openclaw",
    ]
    assert manifest.get("agent_executables") in (None, {})

    pending_rows = [row for row in loaded["cells"] if row["status"] == "pending" and row["run_id"] is None]
    assert len(pending_rows) == 16
    cli_pending = [
        row
        for row in pending_rows
        if row["backend"] in {"no_memory", "hm_arch"}
    ]
    assert len(cli_pending) == 16
    assert all("not found on PATH" in row["rationale"] for row in cli_pending)


def test_production_resolution_ignores_bench_env_override(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PATH", "")
    monkeypatch.setenv("HM_ARCH_BENCH_CODEX_EXECUTABLE", "/bin/false")
    assert resolve_comparison_executable(AgentKind.CODEX, allow_test_double=False) is None


def test_build_matrix_summary_excludes_all_failed_cells_from_tradeoffs() -> None:
    failed_row = HotpotqaCellSummary(
        agent="openclaw",
        backend="hm_arch",
        top_k=5,
        status="run",
        rationale="",
        execution_mode="comparison",
        use_mock_agent=False,
        runner_implementation="openclaw-cli",
        agent_executable="openclaw",
        executable_source="path",
        cli_mode="real",
        run_id="hotpotqa-openclaw-hm_arch-s0-k5-test",
        query_count=5,
        mean_accuracy=0.0,
        mean_retrieval_hit_rate=None,
        mean_supporting_fact_recall=0.0,
        mean_query_time_ms=1500.0,
        p95_query_time_ms=1600.0,
        total_input_tokens=0,
        total_output_tokens=0,
        total_failure_count=5,
        completed_query_count=0,
        index_storage_bytes=None,
    )
    summary = build_matrix_summary(
        cell_summaries=[failed_row],
        output_root=Path("benchmark-results/hotpotqa"),
        execution_mode="comparison",
        use_mock_agent=False,
    )
    assert summary["executed_cells"] == 1
    assert summary["completed_cells"] == 0
    assert summary["failed_cells"] == 1
    assert summary["tradeoffs"] == [
        "No valid completed comparisons: all executed cells recorded agent or recall "
        "failures. See per-query failure_reason and agent_exit_code in queries.jsonl."
    ]


def test_build_matrix_summary_skips_equal_accuracy_tradeoff() -> None:
    hm_row = HotpotqaCellSummary(
        agent="codex",
        backend="hm_arch",
        top_k=5,
        status="run",
        rationale="",
        execution_mode="comparison",
        use_mock_agent=False,
        runner_implementation="codex-cli",
        agent_executable="codex",
        executable_source="path",
        cli_mode="real",
        run_id="run-hm",
        query_count=2,
        mean_accuracy=0.5,
        mean_retrieval_hit_rate=0.5,
        mean_supporting_fact_recall=0.5,
        mean_query_time_ms=100.0,
        p95_query_time_ms=110.0,
        total_input_tokens=100,
        total_output_tokens=10,
        total_failure_count=0,
        completed_query_count=2,
        index_storage_bytes=None,
    )
    nm_row = HotpotqaCellSummary(
        agent="codex",
        backend="no_memory",
        top_k=5,
        status="run",
        rationale="",
        execution_mode="comparison",
        use_mock_agent=False,
        runner_implementation="codex-cli",
        agent_executable="codex",
        executable_source="path",
        cli_mode="real",
        run_id="run-nm",
        query_count=2,
        mean_accuracy=0.5,
        mean_retrieval_hit_rate=0.0,
        mean_supporting_fact_recall=None,
        mean_query_time_ms=50.0,
        p95_query_time_ms=55.0,
        total_input_tokens=50,
        total_output_tokens=5,
        total_failure_count=0,
        completed_query_count=2,
        index_storage_bytes=None,
    )
    summary = build_matrix_summary(
        cell_summaries=[hm_row, nm_row],
        output_root=Path("benchmark-results/hotpotqa"),
        execution_mode="comparison",
        use_mock_agent=False,
    )
    tradeoff_text = " ".join(summary["tradeoffs"])
    assert "0.50 vs 0.50" not in tradeoff_text
    assert "improves answer accuracy" not in tradeoff_text


def test_build_matrix_summary_uses_neutral_metric_comparisons() -> None:
    hm_row = HotpotqaCellSummary(
        agent="codex",
        backend="hm_arch",
        top_k=5,
        status="run",
        rationale="",
        execution_mode="comparison",
        use_mock_agent=False,
        runner_implementation="codex-cli",
        agent_executable="codex",
        executable_source="path",
        cli_mode="real",
        run_id="run-hm",
        query_count=2,
        mean_accuracy=0.25,
        mean_retrieval_hit_rate=0.25,
        mean_supporting_fact_recall=0.25,
        mean_query_time_ms=40.0,
        p95_query_time_ms=45.0,
        total_input_tokens=40,
        total_output_tokens=10,
        total_failure_count=0,
        completed_query_count=2,
        index_storage_bytes=None,
    )
    nm_row = HotpotqaCellSummary(
        agent="codex",
        backend="no_memory",
        top_k=5,
        status="run",
        rationale="",
        execution_mode="comparison",
        use_mock_agent=False,
        runner_implementation="codex-cli",
        agent_executable="codex",
        executable_source="path",
        cli_mode="real",
        run_id="run-nm",
        query_count=2,
        mean_accuracy=0.75,
        mean_retrieval_hit_rate=0.0,
        mean_supporting_fact_recall=None,
        mean_query_time_ms=80.0,
        p95_query_time_ms=85.0,
        total_input_tokens=80,
        total_output_tokens=10,
        total_failure_count=0,
        completed_query_count=2,
        index_storage_bytes=None,
    )
    summary = build_matrix_summary(
        cell_summaries=[hm_row, nm_row],
        output_root=Path("benchmark-results/hotpotqa"),
        execution_mode="comparison",
        use_mock_agent=False,
    )
    tradeoff_text = " ".join(summary["tradeoffs"])
    assert "Answer accuracy comparison" in tradeoff_text
    assert "Mean query time comparison" in tradeoff_text
    assert "Input token comparison" in tradeoff_text
    assert "improves" not in tradeoff_text
    assert "adds latency" not in tradeoff_text
    assert "increase input tokens" not in tradeoff_text
