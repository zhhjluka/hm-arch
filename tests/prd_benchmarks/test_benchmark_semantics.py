"""Benchmark runner semantics and PRD comparison operators (MEM-31)."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from benchmarks.harness import (
    BenchmarkReport,
    build_contract_compliance,
    passes_strict_greater,
    passes_strict_less,
    run_prd_benchmark_suite,
)
from benchmarks.prd_targets import PRD_TARGETS

pytestmark = pytest.mark.benchmark


class TestPrdComparisonOperators:
    def test_strict_less_fails_at_boundary(self) -> None:
        assert not passes_strict_less(100.0, 100.0)
        assert passes_strict_less(99.99, 100.0)

    def test_strict_greater_fails_at_boundary(self) -> None:
        assert not passes_strict_greater(0.80, 0.80)
        assert passes_strict_greater(0.8001, 0.80)

    def test_contract_compliance_uses_strict_less(self) -> None:
        row = build_contract_compliance(
            add_p95_ms=50.0,
            search_p95_ms=100.0,
            consolidate_seconds=60.0,
            storage_mb=500.0,
            test=PRD_TARGETS.test_benchmark,
            week9=PRD_TARGETS.week9_optimization,
        )["test_benchmark"]["search_p95_ms"]
        assert row["pass"] is False
        assert row["comparison"] == "observed < limit"


class TestWeek9NotAcceptanceGate:
    def test_week9_keys_absent_from_acceptance_assertions(self) -> None:
        report = BenchmarkReport(environment={}, targets={})
        report.assertions = {
            "test_benchmark_search_p95": True,
            "test_benchmark_add_p95": True,
        }
        for key in report.assertions:
            assert not key.startswith("week9_")

    def test_week9_miss_does_not_fail_acceptance(self) -> None:
        report = BenchmarkReport(environment={}, targets={})
        report.assertions = {"test_benchmark_search_p95": True}
        report.results["contract_compliance"] = {
            "test_benchmark": {"search_p95_ms": {"pass": True}},
            "week9_optimization": {
                "search_p95_ms": {"pass": False},
                "add_p95_ms": {"pass": True},
                "consolidate_seconds": {"pass": True},
            },
        }
        assert report.acceptance_failures() == []

    def test_runner_succeeds_when_only_week9_search_misses(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Simulate host that passes acceptance but misses Week 9 search <50ms."""
        compliance = build_contract_compliance(
            add_p95_ms=1.0,
            search_p95_ms=73.0,
            consolidate_seconds=1.0,
            storage_mb=10.0,
            test=PRD_TARGETS.test_benchmark,
            week9=PRD_TARGETS.week9_optimization,
        )
        report = BenchmarkReport(environment={}, targets={})
        report.assertions = {
            "test_benchmark_add_p95": compliance["test_benchmark"]["add_p95_ms"]["pass"],
            "test_benchmark_search_p95": compliance["test_benchmark"]["search_p95_ms"][
                "pass"
            ],
            "test_benchmark_consolidate_seconds": compliance["test_benchmark"][
                "consolidate_seconds"
            ]["pass"],
            "test_benchmark_storage_mb": compliance["test_benchmark"]["storage_mb"]["pass"],
        }
        report.results["contract_compliance"] = compliance
        assert compliance["test_benchmark"]["search_p95_ms"]["pass"] is True
        assert compliance["week9_optimization"]["search_p95_ms"]["pass"] is False
        assert report.acceptance_failures() == []

        def fake_suite(_root: Path, targets=None):
            return report

        import scripts.run_prd_benchmarks as runner

        monkeypatch.setattr(runner, "run_prd_benchmark_suite", fake_suite)
        monkeypatch.setattr(sys, "argv", ["run_prd_benchmarks.py"])
        assert runner.main() == 0
