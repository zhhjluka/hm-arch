"""Fast unit tests for PRD benchmark contract semantics (no slow suite)."""

from __future__ import annotations

from benchmarks.harness import BenchmarkReport, _contract_row


def test_contract_row_operators() -> None:
    assert _contract_row(50.0, 50.0, comparison="<=")["pass"]
    assert not _contract_row(50.01, 50.0, comparison="<=")["pass"]
    assert _contract_row(499.9, 500.0, comparison="<")["pass"]
    assert not _contract_row(500.0, 500.0, comparison="<")["pass"]
    assert _contract_row(0.801, 0.80, comparison=">")["pass"]
    assert not _contract_row(0.80, 0.80, comparison=">")["pass"]


def test_acceptance_passes_when_week9_stretch_fails() -> None:
    report = BenchmarkReport(environment={}, targets={})
    report.assertions = {"test_benchmark_add_p95": True}
    report.stretch_assertions = {
        "week9_add_p95": False,
        "week9_search_p95": False,
        "week9_consolidate_seconds": False,
    }
    assert report.acceptance_passed()
