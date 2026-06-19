"""Tests for tau2-bench agent-experience comparison (HM-76 / MEM-76)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from benchmarks.cross_agent.tau2.config import (
    COMPARISON_AGENTS,
    COMPARISON_BACKENDS,
    Tau2Domain,
    tau2_matrix_coordinates,
)
from benchmarks.cross_agent.tau2.fixtures import airline_fixture, get_tau2_domain_fixture, retail_fixture
from benchmarks.cross_agent.tau2.runner import run_tau2_comparison
from benchmarks.cross_agent.types import AgentKind, MemoryBackendKind


def test_tau2_domain_fixtures_cover_retail_and_airline() -> None:
    retail = retail_fixture()
    airline = airline_fixture()
    assert retail.family.value == "tau2_bench"
    assert airline.family.value == "tau2_bench"
    assert all(item.metadata.get("domain") == "retail" for item in retail.ingest_items)
    assert all(item.metadata.get("domain") == "airline" for item in airline.ingest_items)
    assert all(query.task_success_criteria for query in retail.queries)
    assert all(query.task_success_criteria for query in airline.queries)


def test_tau2_matrix_has_full_agent_backend_grid() -> None:
    coordinates = tau2_matrix_coordinates()
    assert len(coordinates) == len(COMPARISON_AGENTS) * len(COMPARISON_BACKENDS)
    keys = {(coord.agent, coord.backend) for coord in coordinates}
    for agent in COMPARISON_AGENTS:
        for backend in COMPARISON_BACKENDS:
            assert (agent, backend) in keys


def test_run_tau2_comparison_writes_artifacts(tmp_path: Path) -> None:
    report = run_tau2_comparison(output_root=tmp_path)
    assert report.issue == "MEM-76"
    assert (tmp_path / "summary_table.json").is_file()
    assert (tmp_path / "summary_table.csv").is_file()
    assert (tmp_path / "matrix_status.json").is_file()
    assert (tmp_path / "openclaw_pending.json").is_file()
    assert (tmp_path / "trajectory_index.jsonl").is_file()
    assert len(report.rows) == len(tau2_matrix_coordinates())


def test_openclaw_cells_are_pending_mem75(tmp_path: Path) -> None:
    report = run_tau2_comparison(output_root=tmp_path)
    openclaw_rows = [row for row in report.rows if row.agent == AgentKind.OPENCLAW.value]
    assert len(openclaw_rows) == len(COMPARISON_BACKENDS)
    assert all(row.status == "pending_mem75" for row in openclaw_rows)
    assert all(row.retail_run_id is None for row in openclaw_rows)

    pending = json.loads((tmp_path / "openclaw_pending.json").read_text(encoding="utf-8"))
    assert pending["issue"] == "MEM-75"
    assert len(pending["cells"]) == len(COMPARISON_BACKENDS)


def test_supported_non_openclaw_cells_complete(tmp_path: Path) -> None:
    report = run_tau2_comparison(output_root=tmp_path)
    executed = [
        row
        for row in report.rows
        if row.agent != AgentKind.OPENCLAW.value and row.status == "completed"
    ]
    assert executed
    for row in executed:
        assert row.retail_run_id
        assert row.airline_run_id
        assert row.retail_trajectory_path
        assert row.airline_trajectory_path
        assert Path(row.retail_trajectory_path).is_file()
        assert Path(row.airline_trajectory_path).is_file()


@pytest.mark.parametrize(
    ("agent", "backend"),
    [
        (AgentKind.CODEX, MemoryBackendKind.NATIVE_MEMORY),
        (AgentKind.CODEX, MemoryBackendKind.MEM0),
        (AgentKind.HERMES, MemoryBackendKind.OPENVIKING),
        (AgentKind.CLAUDE_CODE, MemoryBackendKind.OPENVIKING),
    ],
)
def test_unsupported_cells_are_visible(
    tmp_path: Path,
    agent: AgentKind,
    backend: MemoryBackendKind,
) -> None:
    report = run_tau2_comparison(output_root=tmp_path / f"{agent.value}-{backend.value}")
    row = next(
        row for row in report.rows if row.agent == agent.value and row.backend == backend.value
    )
    assert row.status == "unsupported"
    assert row.rationale
    assert row.retail_run_id is None


def test_hm_arch_beats_no_memory_on_tau2_retail(tmp_path: Path) -> None:
    report = run_tau2_comparison(output_root=tmp_path)
    hm = next(
        row
        for row in report.rows
        if row.agent == AgentKind.CODEX.value and row.backend == MemoryBackendKind.HM_ARCH.value
    )
    none = next(
        row
        for row in report.rows
        if row.agent == AgentKind.CODEX.value and row.backend == MemoryBackendKind.NO_MEMORY.value
    )
    assert hm.retail_mean_accuracy is not None
    assert none.retail_mean_accuracy is not None
    assert hm.retail_mean_accuracy >= none.retail_mean_accuracy


def test_domain_fixtures_are_isolated_by_seed() -> None:
    retail = get_tau2_domain_fixture(Tau2Domain.RETAIL)
    airline = get_tau2_domain_fixture(Tau2Domain.AIRLINE)
    retail_ids = {item.item_id for item in retail.ingest_items}
    airline_ids = {item.item_id for item in airline.ingest_items}
    assert retail_ids.isdisjoint(airline_ids)


def test_executed_runs_use_domain_specific_queries(tmp_path: Path) -> None:
    report = run_tau2_comparison(output_root=tmp_path)
    codex_hm = next(
        row
        for row in report.rows
        if row.agent == AgentKind.CODEX.value and row.backend == MemoryBackendKind.HM_ARCH.value
    )
    retail_lines = Path(codex_hm.retail_trajectory_path).read_text(encoding="utf-8").strip().splitlines()
    airline_lines = Path(codex_hm.airline_trajectory_path).read_text(encoding="utf-8").strip().splitlines()
    retail_rows = [json.loads(line) for line in retail_lines]
    airline_rows = [json.loads(line) for line in airline_lines]
    assert all(row["query_id"].startswith("retail-") for row in retail_rows)
    assert all(row["query_id"].startswith("airline-") for row in airline_rows)
    assert retail_rows[0]["domain"] == "retail"
    assert airline_rows[0]["domain"] == "airline"
