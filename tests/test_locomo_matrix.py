"""Tests for versioned LoCoMo ingestion and matrix orchestration (MEM-78)."""

from __future__ import annotations

import json
import os
import stat
import sys
from pathlib import Path

import pytest

from benchmarks.cross_agent import AgentKind, BenchmarkFamily, BenchmarkRunConfig, MemoryBackendKind
from benchmarks.cross_agent.fixtures.locomo import (
    category_name,
    get_dataset_manifest,
    load_locomo_fixture,
    resolve_dataset_path,
)
from benchmarks.cross_agent.fixtures.locomo.categories import LOCOMO_CATEGORY_NAMES
from benchmarks.cross_agent.fixtures.resolve import resolve_fixture
from benchmarks.cross_agent.locomo_matrix import (
    MatrixRunnerMode,
    locomo_matrix_plans,
    run_locomo_matrix,
)
from benchmarks.cross_agent.metrics import aggregate_by_category
from benchmarks.cross_agent.run_id import derive_run_id
from benchmarks.cross_agent.runner import run_cross_agent_benchmark


REPO_ROOT = Path(__file__).resolve().parents[1]
FAKE_CLI = REPO_ROOT / "tests" / "fixtures" / "fake_agent_cli.py"


def _write_fake_executable(path: Path) -> str:
    script = f"""#!/bin/sh
exec {sys.executable} {FAKE_CLI} "$@"
"""
    path.write_text(script, encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IEXEC)
    return str(path)


def _write_failing_executable(path: Path) -> str:
    script = """#!/bin/sh
if [ "$1" = "exec" ] && [ "$2" = "--help" ]; then
  echo "codex exec help"
  exit 0
fi
if [ "$1" = "agent" ] && [ "$2" = "--help" ]; then
  echo "openclaw agent --message"
  exit 0
fi
if [ "$1" = "--help" ]; then
  echo "agent help --output-format -z --oneshot"
  exit 0
fi
echo '{"access_token":"super-secret-benchmark-token"}' >&2
exit 1
"""
    path.write_text(script, encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IEXEC)
    return str(path)


@pytest.fixture
def fake_executable(tmp_path: Path) -> str:
    return _write_fake_executable(tmp_path / "fake-agent-cli")


@pytest.fixture
def failing_executable(tmp_path: Path) -> str:
    return _write_failing_executable(tmp_path / "failing-agent-cli")


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
        runner_mode=MatrixRunnerMode.MOCK,
        include_openclaw=False,
        max_conversations=1,
    )
    assert summary["report_type"] == "mock_smoke"
    assert summary["runner_mode"] == "mock"
    assert "mock_results" in summary
    assert "real_results" not in summary
    assert summary["completed_run_count"] == 6
    assert summary["unsupported_or_pending_count"] == 14
    assert "exact_command" in summary["provenance"]

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

    completed = summary["mock_results"]
    assert completed
    first_summary = Path(completed[0]["summary_path"])
    assert first_summary.is_file()
    payload = json.loads(first_summary.read_text(encoding="utf-8"))
    assert payload["dataset"]["dataset_id"] == "locomo10-sample"
    assert payload["category_aggregates"]
    for cell in completed:
        assert cell["runner_mode"] == "mock_only"


def test_locomo_matrix_real_cli_smoke_with_fake_executable(
    tmp_path: Path,
    fake_executable: str,
) -> None:
    """Offline smoke for the real-mode code path — not production comparison data."""
    summary = run_locomo_matrix(
        output_root=tmp_path,
        dataset_id="locomo10-sample",
        dataset_version="2024-03-sample",
        runner_mode=MatrixRunnerMode.REAL,
        include_openclaw=False,
        max_conversations=1,
        max_queries=3,
        agent_executable=fake_executable,
        agent_timeout_s=30.0,
    )
    assert summary["report_type"] == "real_cli_comparison"
    assert summary["runner_mode"] == "real"
    assert summary.get("test_double_mode") is True
    assert "real_results" in summary
    assert "mock_results" not in summary
    assert summary["completed_run_count"] == 6
    assert summary["matrix"]["agent_executable"] == fake_executable

    real_cells = summary["real_results"]
    agents = {cell["agent"] for cell in real_cells}
    backends = {cell["backend"] for cell in real_cells}
    assert agents == {"hermes", "claude_code", "codex"}
    assert backends == {"no_memory", "hm_arch"}

    for cell in real_cells:
        assert cell["runner_mode"] in {"real", "benchmark"}
        assert cell["invocations_jsonl_path"]
        invocations_path = Path(cell["invocations_jsonl_path"])
        assert invocations_path.is_file()
        first_line = invocations_path.read_text(encoding="utf-8").splitlines()[0]
        invocation = json.loads(first_line)
        assert invocation["exact_command"]
        assert invocation["argv"]
        assert "stdout" in invocation

        summary_path = Path(cell["summary_path"])
        payload = json.loads(summary_path.read_text(encoding="utf-8"))
        provenance = payload["agent_metadata"].get("runtime_provenance", {})
        assert provenance["agent_cli"]["executable"] == fake_executable
        assert provenance["cli_mode"] in {"real", "benchmark"}


def test_locomo_matrix_real_mode_marks_mem0_cells_unsupported() -> None:
    plans = locomo_matrix_plans(
        include_openclaw=False,
        runner_mode=MatrixRunnerMode.REAL,
    )
    mem0_plans = [plan for plan in plans if plan.backend is MemoryBackendKind.MEM0]
    assert len(mem0_plans) == 4
    openclaw = next(plan for plan in mem0_plans if plan.agent is AgentKind.OPENCLAW)
    assert openclaw.status == "pending"
    assert not openclaw.run
    non_openclaw = [plan for plan in mem0_plans if plan.agent is not AgentKind.OPENCLAW]
    assert all(plan.status == "unsupported" for plan in non_openclaw)
    assert all(not plan.run for plan in non_openclaw)


def test_openclaw_deferral_does_not_reference_completed_mem75() -> None:
    plans = locomo_matrix_plans(
        include_openclaw=False,
        runner_mode=MatrixRunnerMode.REAL,
    )
    openclaw_plans = [plan for plan in plans if plan.agent is AgentKind.OPENCLAW]
    assert openclaw_plans
    assert all("MEM-75" not in plan.rationale for plan in openclaw_plans)


def test_real_matrix_marks_all_failed_cells_failed_and_redacts_invocations(
    tmp_path: Path,
    failing_executable: str,
) -> None:
    summary = run_locomo_matrix(
        output_root=tmp_path,
        dataset_id="locomo10-sample",
        dataset_version="2024-03-sample",
        runner_mode=MatrixRunnerMode.REAL,
        include_openclaw=False,
        max_conversations=1,
        max_queries=1,
        agent_executable=failing_executable,
        agent_timeout_s=10.0,
    )

    assert summary["completed_run_count"] == 0
    assert summary["failed_run_count"] == 6
    assert len(summary["real_results"]) == 6
    for cell in summary["real_results"]:
        assert cell["status"] == "failed"
        assert cell["completed_query_count"] == 0
        assert cell["total_failure_count"] == 1
        invocation = json.loads(
            Path(cell["invocations_jsonl_path"])
            .read_text(encoding="utf-8")
            .splitlines()[0]
        )
        assert "super-secret-benchmark-token" not in json.dumps(invocation)
        assert "<redacted>" in invocation["stderr"]


def test_max_queries_limits_fixture_queries() -> None:
    fixture = load_locomo_fixture(
        "locomo10-sample",
        "2024-03-sample",
        max_conversations=1,
        max_queries=7,
    )
    assert len(fixture.queries) == 7


def test_max_queries_affects_run_id() -> None:
    base = derive_run_id(
        family=BenchmarkFamily.LOCOMO,
        agent=AgentKind.CODEX,
        backend=MemoryBackendKind.HM_ARCH,
        seed=0,
        top_k=5,
        dataset_id="locomo10",
        dataset_version="2024-03",
    )
    limited = derive_run_id(
        family=BenchmarkFamily.LOCOMO,
        agent=AgentKind.CODEX,
        backend=MemoryBackendKind.HM_ARCH,
        seed=0,
        top_k=5,
        dataset_id="locomo10",
        dataset_version="2024-03",
        max_queries=5,
    )
    assert base != limited


def test_locomo_handoff_summary_structure() -> None:
    handoff_dir = (
        REPO_ROOT
        / "benchmarks"
        / "cross_agent"
        / "fixtures"
        / "locomo"
        / "handoff"
    )
    summary_path = handoff_dir / "matrix_summary_real.json"
    if not summary_path.is_file():
        pytest.skip("handoff artifacts not generated in this checkout")

    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    pointer = json.loads(
        (handoff_dir / "matrix_summary.json").read_text(encoding="utf-8")
    )
    assert not Path(pointer["path"]).is_absolute()
    assert summary["report_type"] == "real_cli_comparison"
    assert summary.get("test_double_mode") is False
    assert "real_results" in summary
    assert summary["dataset"]["sha256"]
    assert summary["provenance"]["exact_command"]
    assert "not the official LoCoMo" in summary["metric_definition"]["accuracy"]

    real_cells = summary["real_results"]
    assert len(real_cells) == 8
    agents = {cell["agent"] for cell in real_cells}
    backends = {cell["backend"] for cell in real_cells}
    assert agents == {"openclaw", "hermes", "claude_code", "codex"}
    assert backends == {"no_memory", "hm_arch"}

    for cell in real_cells:
        assert cell["runner_mode"] in {"real", "unavailable"}
        invocations_path = Path(cell["invocations_jsonl_path"])
        assert not invocations_path.is_absolute()
        if cell["status"] == "unavailable":
            continue
        invocations_path = REPO_ROOT / invocations_path
        assert invocations_path.is_file()
        first_line = invocations_path.read_text(encoding="utf-8").splitlines()[0]
        invocation = json.loads(first_line)
        assert invocation["exact_command"]
        assert "fake_agent_cli" not in invocation["exact_command"]
        provenance = cell.get("runtime_provenance", {})
        cli = provenance.get("agent_cli", {})
        assert cli.get("executable")
        assert "fake_agent_cli" not in str(cli.get("executable", ""))
        if cell["completed_query_count"] == 0 and cell["total_failure_count"] > 0:
            assert cell["status"] == "failed"

    assert not list(handoff_dir.glob("locomo-*/storage"))


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
