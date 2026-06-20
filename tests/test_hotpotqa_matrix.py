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
    assert loaded["mock_smoke_cells"] == 12
    assert loaded.get("test_double_cells", 0) == 0
    assert loaded["pending_cells"] == 4
    assert loaded["unsupported_cells"] == 24
    assert len(loaded["cells"]) == 40
    assert manifest["execution_mode"] == "mock_smoke"

    mock_rows = [row for row in loaded["cells"] if row["run_id"]]
    assert len(mock_rows) == 12
    for row in mock_rows:
        assert row["use_mock_agent"] is True
        assert row["runner_implementation"] == "mock-synthetic"
        run_dir = tmp_path / row["run_id"]
        assert (run_dir / "summary.json").is_file()
        assert (run_dir / "queries.jsonl").is_file()
        assert (run_dir / "retrieval_evidence.jsonl").is_file()

    pending_dirs = list((tmp_path / "pending").glob("*/status.json"))
    assert len(pending_dirs) == 4

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
    assert loaded["test_double_cells"] == 12
    assert loaded["mock_smoke_cells"] == 0
    assert loaded["agent_executables"] is not None

    test_double_rows = [
        row for row in loaded["cells"] if row["run_id"] and row["executable_source"] == "fake_double"
    ]
    assert len(test_double_rows) == 12
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


def test_run_hotpotqa_matrix_comparison_without_cli_marks_pending(tmp_path: Path) -> None:
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
    assert sorted(manifest.get("agent_cli_unavailable") or []) == ["claude_code", "codex", "hermes"]
    assert manifest.get("agent_executables") in (None, {})

    pending_rows = [row for row in loaded["cells"] if row["status"] == "pending" and row["run_id"] is None]
    assert len(pending_rows) == 16
    cli_pending = [
        row
        for row in pending_rows
        if row["agent"] in {"codex", "claude_code", "hermes"} and row["backend"] in {"no_memory", "hm_arch"}
    ]
    assert len(cli_pending) == 12
    assert all("not found on PATH" in row["rationale"] for row in cli_pending)
