"""Tests for HotpotQA matrix execution (MEM-77)."""

from __future__ import annotations

import json
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
from benchmarks.cross_agent.types import AgentKind, BenchmarkFamily, MemoryBackendKind


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
    assert expected_runnable_cell_count() == 12
    runnable = runnable_non_openclaw_cells()
    assert all(cell.agent is not AgentKind.OPENCLAW for cell in runnable)
    assert all(cell.status is CellStatus.RUN for cell in runnable)


def test_openclaw_real_cells_are_pending() -> None:
    pending = [
        cell
        for cell in iter_hotpotqa_matrix_cells()
        if cell.agent is AgentKind.OPENCLAW
        and cell.backend in {MemoryBackendKind.NO_MEMORY, MemoryBackendKind.HM_ARCH}
    ]
    assert len(pending) == 4
    assert all(cell.status is CellStatus.PENDING for cell in pending)


def test_run_hotpotqa_matrix_writes_artifacts(tmp_path: Path) -> None:
    summary = run_hotpotqa_matrix(output_root=tmp_path, seed=0, use_mock_agent=True)
    summary_path = tmp_path / "matrix_summary.json"
    assert summary_path.is_file()
    loaded = json.loads(summary_path.read_text(encoding="utf-8"))
    assert loaded["subset_version"] == HOTPOTQA_SUBSET_VERSION
    assert loaded["subset_hash"] == compute_subset_hash()
    assert loaded["executed_cells"] == 12
    assert loaded["pending_cells"] == 4
    assert loaded["unsupported_cells"] == 24
    assert len(loaded["cells"]) == 40
    assert loaded["tradeoffs"]

    executed = [row for row in loaded["cells"] if row["run_id"]]
    assert len(executed) == 12
    for row in executed:
        run_dir = tmp_path / row["run_id"]
        assert (run_dir / "summary.json").is_file()
        assert (run_dir / "queries.jsonl").is_file()
        assert (run_dir / "retrieval_evidence.jsonl").is_file()

    hm_arch_k5 = next(
        row
        for row in executed
        if row["backend"] == "hm_arch" and row["top_k"] == 5 and row["agent"] == "codex"
    )
    assert hm_arch_k5["mean_accuracy"] is not None
    assert hm_arch_k5["mean_accuracy"] > 0.0
    assert hm_arch_k5["mean_retrieval_hit_rate"] is not None
    assert hm_arch_k5["mean_retrieval_hit_rate"] > 0.0

    no_memory = next(row for row in executed if row["backend"] == "no_memory")
    assert no_memory["mean_accuracy"] == 0.0
    assert no_memory["mean_retrieval_hit_rate"] == 0.0
    assert hm_arch_k5["mean_accuracy"] > no_memory["mean_accuracy"]

    pending_dirs = list((tmp_path / "pending").glob("*/status.json"))
    assert len(pending_dirs) == 4

    config = load_hotpotqa_config()
    assert summary["answer_prompt_template"] == config["answer_prompt_template"]
