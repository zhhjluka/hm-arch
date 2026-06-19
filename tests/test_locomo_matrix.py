"""Tests for versioned LoCoMo ingestion and matrix orchestration (MEM-78)."""

from __future__ import annotations

import json
from pathlib import Path

from benchmarks.cross_agent import AgentKind, BenchmarkFamily, BenchmarkRunConfig, MemoryBackendKind
from benchmarks.cross_agent.fixtures.locomo import (
    category_name,
    get_dataset_manifest,
    load_locomo_fixture,
    resolve_dataset_path,
)
from benchmarks.cross_agent.fixtures.locomo.categories import LOCOMO_CATEGORY_NAMES
from benchmarks.cross_agent.fixtures.resolve import resolve_fixture
from benchmarks.cross_agent.locomo_matrix import run_locomo_matrix
from benchmarks.cross_agent.metrics import aggregate_by_category
from benchmarks.cross_agent.run_id import derive_run_id
from benchmarks.cross_agent.runner import run_cross_agent_benchmark


def test_locomo_category_mapping_matches_official_order() -> None:
    assert LOCOMO_CATEGORY_NAMES == {
        1: "multi_hop",
        2: "temporal",
        3: "open_domain",
        4: "single_hop",
        5: "adversarial",
    }
    assert category_name(2) == "temporal"


def test_locomo_manifest_checksum_validation() -> None:
    manifest = get_dataset_manifest("locomo10")
    assert manifest.version == "2024-03"
    assert manifest.sha256 == "79fa87e90f04081343b8c8debecb80a9a6842b76a7aa537dc9fdf651ea698ff4"
    path = resolve_dataset_path("locomo10")
    assert path.name == "locomo10.json"


def test_locomo_sample_loader_maps_evidence_and_categories() -> None:
    fixture = load_locomo_fixture("locomo10-sample", "2024-03-sample")
    assert fixture.family is BenchmarkFamily.LOCOMO
    assert len(fixture.ingest_items) > 0
    assert len(fixture.queries) == 199

    categories = {query.metadata["category_name"] for query in fixture.queries}
    assert "temporal" in categories
    assert "adversarial" in categories

    adversarial = [q for q in fixture.queries if q.metadata["category"] == 5]
    assert adversarial
    assert adversarial[0].expected_answer is None
    assert adversarial[0].metadata["unanswerable"] is True

    answered = next(q for q in fixture.queries if q.metadata["category"] != 5)
    assert answered.expected_memory_ids
    assert answered.expected_memory_ids[0].startswith("D")


def test_dataset_fields_affect_run_id() -> None:
    base = derive_run_id(
        family=BenchmarkFamily.LOCOMO,
        agent=AgentKind.CODEX,
        backend=MemoryBackendKind.HM_ARCH,
        seed=0,
        top_k=5,
    )
    with_dataset = derive_run_id(
        family=BenchmarkFamily.LOCOMO,
        agent=AgentKind.CODEX,
        backend=MemoryBackendKind.HM_ARCH,
        seed=0,
        top_k=5,
        dataset_id="locomo10",
        dataset_version="2024-03",
    )
    assert base != with_dataset


def test_resolve_fixture_uses_locomo_loader_when_configured() -> None:
    config = BenchmarkRunConfig(
        family=BenchmarkFamily.LOCOMO,
        agent=AgentKind.CODEX,
        backend=MemoryBackendKind.HM_ARCH,
        dataset_id="locomo10-sample",
        dataset_version="2024-03-sample",
        max_conversations=1,
    )
    fixture = resolve_fixture(config)
    assert len(fixture.queries) == 199


def test_locomo_matrix_marks_openclaw_pending_and_runs_non_openclaw_cells(
    tmp_path: Path,
) -> None:
    summary = run_locomo_matrix(
        output_root=tmp_path,
        dataset_id="locomo10-sample",
        dataset_version="2024-03-sample",
        use_mock_agent=True,
        include_openclaw=False,
        max_conversations=1,
    )
    assert summary["completed_run_count"] == 6
    assert summary["unsupported_or_pending_count"] == 14

    openclaw_cells = [cell for cell in summary["cells"] if cell["agent"] == "openclaw"]
    assert len(openclaw_cells) == 5
    assert all(cell["status"] == "pending" for cell in openclaw_cells)

    native_cells = [
        cell
        for cell in summary["cells"]
        if cell["backend"] == "native_memory" and cell["agent"] != "openclaw"
    ]
    assert len(native_cells) == 3
    assert all(cell["status"] == "unsupported" for cell in native_cells)

    completed = [cell for cell in summary["cells"] if cell.get("run_id")]
    assert completed
    first_summary = Path(completed[0]["summary_path"])
    assert first_summary.is_file()
    payload = json.loads(first_summary.read_text(encoding="utf-8"))
    assert payload["dataset"]["dataset_id"] == "locomo10-sample"
    assert payload["category_aggregates"]


def test_category_aggregation_groups_by_locomo_category(tmp_path: Path) -> None:
    fixture = load_locomo_fixture("locomo10-sample", "2024-03-sample", max_conversations=1)
    result = run_cross_agent_benchmark(
        BenchmarkRunConfig(
            family=BenchmarkFamily.LOCOMO,
            agent=AgentKind.CODEX,
            backend=MemoryBackendKind.NO_MEMORY,
            dataset_id="locomo10-sample",
            dataset_version="2024-03-sample",
            max_conversations=1,
            resume=False,
            use_mock_agent=True,
        ),
        output_root=tmp_path,
    )
    grouped = aggregate_by_category(result.queries, fixture.queries)
    assert "temporal" in grouped
    assert grouped["temporal"]["query_count"] > 0
