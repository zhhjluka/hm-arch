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
    check_benchmark_doc_claims,
    check_docs_mention_openclaw,
    check_openclaw_plugin_version,
    check_release_notes,
    check_version_not_already_published,
    is_git_tracked,
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


def test_openclaw_plugin_version_matches_python() -> None:
    from scripts.verify_release_versions import read_python_version

    assert check_openclaw_plugin_version(read_python_version()) == []


def test_docs_mention_openclaw() -> None:
    assert check_docs_mention_openclaw() == []


def test_release_notes_cover_openclaw_and_benchmarks() -> None:
    from scripts.verify_release_versions import read_python_version

    assert check_release_notes(read_python_version()) == []


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
    assert check_version_not_already_published("2.0.5") == []


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


def test_release_gate_rejects_already_published_target(monkeypatch: pytest.MonkeyPatch) -> None:
    from scripts import validate_release_gate as gate

    monkeypatch.setattr(gate, "git_tag_exists", lambda version: version == "2.0.5")
    monkeypatch.setattr(gate, "read_python_version", lambda: "2.0.5")
    monkeypatch.setattr(gate, "run_verify_release_versions", lambda: [])
    monkeypatch.setattr(gate, "check_openclaw_plugin_version", lambda _v: [])
    monkeypatch.setattr(gate, "check_docs_mention_openclaw", lambda: [])
    monkeypatch.setattr(gate, "check_release_notes", lambda _v: [])
    monkeypatch.setattr(gate, "validate_locomo_handoff", lambda: [])
    monkeypatch.setattr(gate, "validate_hotpotqa_artifacts", lambda: [])
    monkeypatch.setattr(gate, "validate_tau2_artifacts", lambda: [])
    monkeypatch.setattr(gate, "check_benchmark_doc_claims", lambda: [])

    with mock.patch.object(sys, "argv", ["validate_release_gate.py"]):
        assert gate.main() == 1
