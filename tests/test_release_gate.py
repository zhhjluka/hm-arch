"""Offline tests for MEM-79 release gate validation."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.validate_release_gate import (  # noqa: E402
    check_docs_mention_openclaw,
    check_openclaw_plugin_version,
    check_release_notes,
    validate_locomo_handoff,
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
    assert check_release_notes() == []


def test_locomo_handoff_has_openclaw_and_provenance() -> None:
    if not HANDOFF.is_file():
        pytest.skip("LoCoMo handoff artifact not present")
    issues = [line for line in validate_locomo_handoff() if not line.startswith("INFO: ")]
    assert issues == []

    summary = json.loads(HANDOFF.read_text(encoding="utf-8"))
    openclaw = [cell for cell in summary["cells"] if cell["agent"] == "openclaw"]
    assert len(openclaw) == 5
    assert all(cell["status"] in {"unavailable", "unsupported"} for cell in openclaw)
