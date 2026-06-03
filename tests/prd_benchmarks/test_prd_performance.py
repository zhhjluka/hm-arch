"""PRD scale and performance benchmarks (HM-31 / MEM-31).

Run explicitly (not part of default CI)::

    uv run pytest tests/prd_benchmarks -m benchmark -v
    uv run python scripts/run_prd_benchmarks.py

Long-run retention and archive expectations for 30 days are covered by::

    uv run pytest tests/test_simulation_30_day.py
    uv run pytest tests/prd_benchmarks/test_prd_thirty_day_archive.py -m benchmark -v
"""

from __future__ import annotations

import json

import pytest

from benchmarks.harness import passes_strict_greater, passes_strict_less, run_prd_benchmark_suite
from benchmarks.prd_targets import PRD_TARGETS

pytestmark = pytest.mark.benchmark


@pytest.fixture(scope="module")
def prd_benchmark_report(tmp_path_factory) -> dict:
    root = tmp_path_factory.mktemp("prd_bench")
    report = run_prd_benchmark_suite(root, PRD_TARGETS)
    return json.loads(report.to_json())


class TestPrdTestBenchmarkContract:
    """PRD test-benchmark table (strict < limits; storage < 500MB)."""

    def test_add_p95_within_test_benchmark(self, prd_benchmark_report: dict) -> None:
        row = prd_benchmark_report["results"]["contract_compliance"]["test_benchmark"][
            "add_p95_ms"
        ]
        assert prd_benchmark_report["assertions"]["test_benchmark_add_p95"]
        assert row["pass"]
        assert passes_strict_less(
            row["observed"], PRD_TARGETS.test_benchmark.add_p95_ms
        )

    def test_search_p95_at_10k_within_test_benchmark(
        self, prd_benchmark_report: dict
    ) -> None:
        row = prd_benchmark_report["results"]["contract_compliance"]["test_benchmark"][
            "search_p95_ms"
        ]
        assert prd_benchmark_report["assertions"]["test_benchmark_search_p95"]
        assert row["pass"]
        assert passes_strict_less(
            row["observed"], PRD_TARGETS.test_benchmark.search_p95_ms
        )

    def test_consolidate_10k_within_test_benchmark(
        self, prd_benchmark_report: dict
    ) -> None:
        row = prd_benchmark_report["results"]["contract_compliance"]["test_benchmark"][
            "consolidate_seconds"
        ]
        assert prd_benchmark_report["assertions"]["test_benchmark_consolidate_seconds"]
        assert row["pass"]

    def test_storage_under_500mb(self, prd_benchmark_report: dict) -> None:
        storage = prd_benchmark_report["results"]["storage_10k_l2_5k_l3"]
        row = prd_benchmark_report["results"]["contract_compliance"]["test_benchmark"][
            "storage_mb"
        ]
        assert prd_benchmark_report["assertions"]["test_benchmark_storage_mb"]
        assert passes_strict_less(
            storage["storage_size_mb"], PRD_TARGETS.test_benchmark.storage_max_mb
        )
        assert row["pass"]


class TestPrdWeek9OptimizationContract:
    """Week 9 stretch — contract_compliance only, not acceptance assertions."""

    def test_week9_contract_reported(self, prd_benchmark_report: dict) -> None:
        week9 = prd_benchmark_report["results"]["contract_compliance"]["week9_optimization"]
        assert "add_p95_ms" in week9
        assert "search_p95_ms" in week9
        assert "consolidate_seconds" in week9
        for row in week9.values():
            assert row["comparison"] == "observed < limit"

    def test_week9_not_in_acceptance_assertions(
        self, prd_benchmark_report: dict
    ) -> None:
        for key in prd_benchmark_report["assertions"]:
            assert not key.startswith("week9_")


class TestPrdScaleConsolidation:
    def test_consolidate_extracts_semantics_at_10k_l2(
        self, prd_benchmark_report: dict
    ) -> None:
        assert prd_benchmark_report["assertions"]["consolidate_extracted_semantics"]
        extracted = prd_benchmark_report["results"]["consolidate_at_10k_l2"][
            "extracted_semantics"
        ]
        assert extracted >= 1


class TestPrdStorageAndLayers:
    def test_storage_measured_for_10k_l2_and_5k_l3(
        self, prd_benchmark_report: dict
    ) -> None:
        storage = prd_benchmark_report["results"]["storage_10k_l2_5k_l3"]
        assert prd_benchmark_report["assertions"]["l2_count_at_least_10k"]
        assert prd_benchmark_report["assertions"]["l3_count_at_least_5k"]
        assert storage["l2_count"] >= PRD_TARGETS.l2_episode_count
        assert storage["l3_active_count"] >= PRD_TARGETS.l3_triple_count

    def test_l4_archive_smoke(self, prd_benchmark_report: dict) -> None:
        assert prd_benchmark_report["assertions"]["l4_smoke_archived_rows"]
        assert prd_benchmark_report["assertions"]["l4_smoke_files_on_disk"]


class TestPrdL4ArchiveScenarios:
    def test_prd_retention_archive_deviation_documented(
        self, prd_benchmark_report: dict
    ) -> None:
        note = prd_benchmark_report["results"]["l4_prd_retention_archive_deviation"]
        assert "l2_archive_threshold" in note
        assert note["modeled_l2_retention_at_30d"] >= note["l2_archive_threshold"]

    def test_uniform_30d_does_not_satisfy_prd_archive_formula(
        self, prd_benchmark_report: dict
    ) -> None:
        uniform = prd_benchmark_report["results"]["l4_archive_10k_uniform_30d"]
        assert prd_benchmark_report["assertions"]["l4_uniform_30d_no_archive_while_above_threshold"]
        assert prd_benchmark_report["assertions"]["l4_uniform_30d_prd_formula_not_satisfied"]
        assert uniform["archived_l4_rows"] == 0
        assert not uniform["prd_formula_matches_observed"]

    def test_mixed_age_exercises_archive_threshold_capacity(
        self, prd_benchmark_report: dict
    ) -> None:
        mixed = prd_benchmark_report["results"]["l4_archive_10k_mixed_age"]
        assert prd_benchmark_report["assertions"]["l4_mixed_age_old_cohort_archived"]
        assert prd_benchmark_report["assertions"]["l4_mixed_age_young_cohort_active"]
        assert mixed["old_cohort_fully_archived"]
        assert mixed["young_cohort_remains_active"]


class TestPrdSevenDaySemantic:
    def test_seven_day_50_conversations_per_day(
        self, prd_benchmark_report: dict
    ) -> None:
        assert prd_benchmark_report["assertions"]["seven_day_conversation_volume"]
        seven = prd_benchmark_report["results"]["seven_day_semantic"]
        assert seven["conversations_per_day"] == PRD_TARGETS.seven_day_conversations_per_day
        assert seven["total_conversations"] == 350

    def test_seven_day_semantic_accuracy_above_80_percent(
        self, prd_benchmark_report: dict
    ) -> None:
        assert prd_benchmark_report["assertions"]["seven_day_semantic_accuracy"]
        accuracy = prd_benchmark_report["results"]["seven_day_semantic"]["semantic_accuracy"]
        assert passes_strict_greater(
            accuracy, PRD_TARGETS.seven_day_min_semantic_accuracy
        )
