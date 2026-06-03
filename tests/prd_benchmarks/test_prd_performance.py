"""PRD scale and performance benchmarks (HM-31 / MEM-31).

Run explicitly (not part of default CI)::

    uv run pytest tests/prd_benchmarks -m benchmark -v
    uv run python scripts/run_prd_benchmarks.py

Long-run retention and archive expectations for 30 days are covered by::

    uv run pytest tests/test_simulation_30_day.py
"""

from __future__ import annotations

import json

import pytest

from benchmarks.harness import run_prd_benchmark_suite
from benchmarks.prd_targets import PRD_TARGETS

pytestmark = pytest.mark.benchmark


@pytest.fixture(scope="module")
def prd_benchmark_report(tmp_path_factory) -> dict:
    root = tmp_path_factory.mktemp("prd_bench")
    report = run_prd_benchmark_suite(root, PRD_TARGETS)
    return json.loads(report.to_json())


class TestPrdTestBenchmarkContract:
    """PRD test-benchmark table (50ms / 100ms / 60s / 500MB)."""

    def test_add_p95_within_test_benchmark(self, prd_benchmark_report: dict) -> None:
        row = prd_benchmark_report["results"]["contract_compliance"]["test_benchmark"][
            "add_p95_ms"
        ]
        assert prd_benchmark_report["assertions"]["test_benchmark_add_p95"]
        assert row["pass"]
        assert row["comparison"] == "<="
        assert row["observed"] <= row["limit"]

    def test_search_p95_at_10k_within_test_benchmark(
        self, prd_benchmark_report: dict
    ) -> None:
        row = prd_benchmark_report["results"]["contract_compliance"]["test_benchmark"][
            "search_p95_ms"
        ]
        assert prd_benchmark_report["assertions"]["test_benchmark_search_p95"]
        assert row["pass"]
        assert row["comparison"] == "<="
        assert row["observed"] <= PRD_TARGETS.test_benchmark.search_p95_ms

    def test_consolidate_10k_within_test_benchmark(
        self, prd_benchmark_report: dict
    ) -> None:
        row = prd_benchmark_report["results"]["contract_compliance"]["test_benchmark"][
            "consolidate_seconds"
        ]
        assert prd_benchmark_report["assertions"]["test_benchmark_consolidate_seconds"]
        assert row["pass"]
        assert row["comparison"] == "<="

    def test_storage_under_500mb(self, prd_benchmark_report: dict) -> None:
        storage = prd_benchmark_report["results"]["storage_10k_l2_5k_l3"]
        row = prd_benchmark_report["results"]["contract_compliance"]["test_benchmark"][
            "storage_mb"
        ]
        assert prd_benchmark_report["assertions"]["test_benchmark_storage_mb"]
        assert storage["storage_size_mb"] < PRD_TARGETS.test_benchmark.storage_max_mb
        assert row["pass"]
        assert row["comparison"] == "<"


class TestPrdWeek9OptimizationContract:
    """PRD Week 9 stretch targets — reported separately from acceptance."""

    def test_week9_contract_reported(self, prd_benchmark_report: dict) -> None:
        week9 = prd_benchmark_report["results"]["contract_compliance"]["week9_optimization"]
        assert "add_p95_ms" in week9
        assert "search_p95_ms" in week9
        assert "consolidate_seconds" in week9
        assert week9["add_p95_ms"]["comparison"] == "<"

    def test_week9_pass_flags_in_stretch_assertions(
        self, prd_benchmark_report: dict
    ) -> None:
        """Week 9 stretch goals are evaluated but excluded from acceptance gates."""
        stretch = prd_benchmark_report["stretch_assertions"]
        assert "week9_add_p95" in stretch
        assert "week9_search_p95" in stretch
        assert "week9_consolidate_seconds" in stretch
        for key in ("week9_add_p95", "week9_search_p95", "week9_consolidate_seconds"):
            assert key not in prd_benchmark_report["assertions"]

        week9 = prd_benchmark_report["results"]["contract_compliance"]["week9_optimization"]
        assert stretch["week9_add_p95"] == week9["add_p95_ms"]["pass"]
        assert stretch["week9_search_p95"] == week9["search_p95_ms"]["pass"]
        assert stretch["week9_consolidate_seconds"] == week9["consolidate_seconds"]["pass"]


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
    def test_l4_mixed_age_matches_injected_old_fraction(
        self, prd_benchmark_report: dict
    ) -> None:
        stats = prd_benchmark_report["results"]["l4_archive_mixed_age"]
        assert prd_benchmark_report["assertions"]["l4_archive_mixed_age_within_range"]
        assert stats["within_expected_range"]
        low, high = stats["expected_range"]
        assert low <= stats["archived_l4_rows"] <= high
        assert stats["expected_archived_by_old_fraction"] == stats["old_episode_count"]

    def test_l4_uniform_30d_reports_prd_inconsistency(
        self, prd_benchmark_report: dict
    ) -> None:
        stats = prd_benchmark_report["results"]["l4_uniform_30d"]
        assert prd_benchmark_report["assertions"]["l4_uniform_30d_retention_above_threshold"]
        assert prd_benchmark_report["assertions"]["l4_uniform_30d_no_mass_archive"]
        assert stats["retention_at_30d"] > stats["l2_archive_threshold"]
        assert stats["archived_l4_rows"] == 0
        assert stats["active_l2_rows"] == PRD_TARGETS.l2_episode_count
        assert (
            stats["prd_inconsistency"]["formula_would_archive_count"]
            > stats["archived_l4_rows"]
        )


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
        seven = prd_benchmark_report["results"]["seven_day_semantic"]
        accuracy = seven["semantic_accuracy"]
        contract = seven["accuracy_contract"]
        assert contract["comparison"] == ">"
        assert contract["pass"] == (accuracy > contract["limit"])
        assert accuracy > PRD_TARGETS.seven_day_min_semantic_accuracy
