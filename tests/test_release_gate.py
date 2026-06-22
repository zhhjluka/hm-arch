"""Offline tests for MEM-79 release gate validation."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from unittest import mock

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.validate_release_gate import (  # noqa: E402
    _classify_hotpotqa_cell_outcome,
    _derive_hotpotqa_counts,
    check_benchmark_doc_claims,
    check_docs_mention_openclaw,
    check_openclaw_plugin_version,
    check_release_readiness_doc,
    check_release_target_alignment,
    check_version_not_already_published,
    is_git_tracked,
    main,
    run_readiness_checks,
    validate_hotpotqa_artifacts,
    validate_locomo_handoff,
    validate_tau2_artifacts,
)

HANDOFF = (
    REPO_ROOT
    / "benchmarks"
    / "cross_agent"
    / "fixtures"
    / "locomo"
    / "handoff"
    / "matrix_summary_real.json"
)
HOTPOTQA_SUMMARY = REPO_ROOT / "benchmark-results" / "hotpotqa" / "matrix_summary.json"
TAU2_MATRIX_STATUS = REPO_ROOT / "benchmark-results" / "tau2-comparison" / "matrix_status.json"


def test_release_gate_script_exits_zero() -> None:
    result = subprocess.run(
        [sys.executable, str(REPO_ROOT / "scripts" / "validate_release_gate.py")],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr or result.stdout
    assert "mode=readiness (version-neutral)" in result.stdout


def test_openclaw_plugin_version_matches_python() -> None:
    from scripts.verify_release_versions import read_python_version

    assert check_openclaw_plugin_version(read_python_version()) == []


def test_docs_mention_openclaw() -> None:
    assert check_docs_mention_openclaw() == []


def test_release_readiness_doc_covers_openclaw_and_benchmarks() -> None:
    assert check_release_readiness_doc() == []


def test_locomo_handoff_has_openclaw_and_provenance() -> None:
    if not HANDOFF.is_file():
        pytest.skip("LoCoMo handoff artifact not present")
    issues = [line for line in validate_locomo_handoff() if not line.startswith("INFO: ")]
    assert issues == []

    summary = json.loads(HANDOFF.read_text(encoding="utf-8"))
    openclaw = [cell for cell in summary["cells"] if cell["agent"] == "openclaw"]
    assert len(openclaw) == 5
    assert all(cell["status"] in {"unavailable", "unsupported"} for cell in openclaw)


def test_hotpotqa_artifact_is_git_tracked_and_audited() -> None:
    if not HOTPOTQA_SUMMARY.is_file():
        pytest.skip("HotpotQA artifact not present")
    assert is_git_tracked(HOTPOTQA_SUMMARY)
    issues = [line for line in validate_hotpotqa_artifacts() if not line.startswith("INFO: ")]
    assert issues == []

    summary = json.loads(HOTPOTQA_SUMMARY.read_text(encoding="utf-8"))
    derived = _derive_hotpotqa_counts(summary["cells"])
    assert derived == {
        "completed": summary["completed_cells"],
        "failed": summary["failed_cells"],
        "pending": summary["pending_cells"],
        "unsupported": summary["unsupported_cells"],
        "run": 0,
    }
    info = " ".join(line for line in validate_hotpotqa_artifacts() if line.startswith("INFO: "))
    assert "4 completed, 4 failed, 8 pending, 24 unsupported" in info


def test_hotpotqa_run_row_outcome_classification() -> None:
    successful = {
        "status": "run",
        "completed_query_count": 5,
        "total_failure_count": 0,
        "mean_accuracy": 0.6,
    }
    failed = {
        "status": "run",
        "completed_query_count": 0,
        "total_failure_count": 5,
        "mean_accuracy": 0.0,
    }
    assert _classify_hotpotqa_cell_outcome(successful) == "completed"
    assert _classify_hotpotqa_cell_outcome(failed) == "failed"


def test_hotpotqa_gate_rejects_counter_mismatch(monkeypatch: pytest.MonkeyPatch) -> None:
    from scripts import validate_release_gate as gate

    payload = {
        "cells": [
            {
                "status": "run",
                "completed_query_count": 5,
                "total_failure_count": 0,
            },
        ],
        "completed_cells": 0,
        "failed_cells": 0,
        "pending_cells": 0,
        "unsupported_cells": 0,
    }

    def fake_read_text(self: Path, encoding: str = "utf-8") -> str:  # noqa: ARG001
        if self == gate.HOTPOTQA_SUMMARY:
            return json.dumps(payload)
        raise AssertionError(f"unexpected read_text: {self}")

    monkeypatch.setattr(gate, "is_git_tracked", lambda _path: True)
    monkeypatch.setattr(Path, "read_text", fake_read_text)
    errors = gate.validate_hotpotqa_artifacts()
    assert any("completed_cells=0 does not match derived completed count 1" in err for err in errors)


def test_tau2_artifact_is_git_tracked_and_audited() -> None:
    if not TAU2_MATRIX_STATUS.is_file():
        pytest.skip("tau2 artifact not present")
    assert is_git_tracked(TAU2_MATRIX_STATUS)
    issues = [line for line in validate_tau2_artifacts() if not line.startswith("INFO: ")]
    assert issues == []


def test_benchmark_docs_do_not_falsely_claim_uncommitted() -> None:
    assert check_benchmark_doc_claims() == []


def test_published_version_gate_rejects_existing_tag() -> None:
    assert check_version_not_already_published("2.0.4") != []


def test_release_target_alignment_rejects_published_version() -> None:
    errors = check_release_target_alignment("2.0.4")
    assert any("already published" in error for error in errors)


def test_release_gate_rejects_false_not_committed_docs(monkeypatch: pytest.MonkeyPatch) -> None:
    from scripts import validate_release_gate as gate

    fake_docs = "HotpotQA benchmark-results/hotpotqa/ is not committed in this release."

    def fake_is_git_tracked(path: Path) -> bool:
        return path.name == "matrix_summary.json"

    def fake_read_text(self: Path, encoding: str = "utf-8") -> str:  # noqa: ARG001
        if self == gate.CROSS_AGENT_DOCS:
            return fake_docs
        if self == gate.CHANGELOG:
            return "# Changelog\n"
        raise AssertionError(f"unexpected read_text: {self}")

    monkeypatch.setattr(gate, "is_git_tracked", fake_is_git_tracked)
    monkeypatch.setattr(Path, "read_text", fake_read_text)
    errors = gate.check_benchmark_doc_claims()
    assert any("falsely claims HotpotQA" in error for error in errors)


def test_hotpotqa_gate_rejects_pending_cells_with_metric_claims() -> None:
    from scripts.validate_release_gate import _blocked_cells_with_metric_claims

    cells = [
        {
            "agent": "openclaw",
            "backend": "hm_arch",
            "top_k": 5,
            "status": "pending",
            "mean_accuracy": 0.75,
        },
    ]
    blocked = _blocked_cells_with_metric_claims(cells)
    assert blocked
    assert "pending" in blocked[0]


def test_release_gate_release_mode_requires_alignment(monkeypatch: pytest.MonkeyPatch) -> None:
    from scripts import validate_release_gate as gate

    monkeypatch.setattr(gate, "run_readiness_checks", lambda: [])
    monkeypatch.setattr(gate, "read_python_version", lambda: "2.0.4")
    monkeypatch.setattr(gate, "git_tag_exists", lambda version: version == "2.0.4")

    assert main(["--target-version", "2.0.4"]) == 1


def test_readiness_checks_do_not_require_release_notes(monkeypatch: pytest.MonkeyPatch) -> None:
    from scripts import validate_release_gate as gate

    monkeypatch.setattr(gate, "run_verify_release_versions", lambda: [])
    monkeypatch.setattr(gate, "check_openclaw_plugin_version", lambda _v: [])
    monkeypatch.setattr(gate, "check_docs_mention_openclaw", lambda: [])
    monkeypatch.setattr(gate, "check_release_readiness_doc", lambda: [])
    monkeypatch.setattr(gate, "check_readiness_docs_do_not_speculate_next_version", lambda: [])
    monkeypatch.setattr(gate, "validate_locomo_handoff", lambda: [])
    monkeypatch.setattr(gate, "validate_hotpotqa_artifacts", lambda: [])
    monkeypatch.setattr(gate, "validate_tau2_artifacts", lambda: [])
    monkeypatch.setattr(gate, "check_benchmark_doc_claims", lambda: [])

    assert run_readiness_checks() == []


def test_no_speculative_version_references_remain() -> None:
    readme = (REPO_ROOT / "README.md").read_text(encoding="utf-8")
    assert "2.0.5" not in readme
    assert (REPO_ROOT / "docs" / "RELEASE_NOTES_v2.0.5.md").is_file() is False
