"""PRD scale and performance benchmarks (HM-31 / MEM-31).

Run explicitly (not part of default CI)::

    uv run pytest tests/prd_benchmarks -m benchmark -v
    uv run python scripts/run_prd_benchmarks.py

Long-run retention and archive expectations for 30 days are covered by::

    uv run pytest tests/test_simulation_30_day.py
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from benchmarks.harness import run_prd_benchmark_suite
from benchmarks.prd_targets import PRD_TARGETS

pytestmark = pytest.mark.benchmark


@pytest.fixture(scope="module")
def prd_benchmark_report(tmp_path_factory) -> dict:
    root = tmp_path_factory.mktemp("prd_bench")
    report = run_prd_benchmark_suite(root, PRD_TARGETS)
    return json.loads(report.to_json())


class TestPrdLatencyTargets:
    def test_add_p95_within_prd_target(self, prd_benchmark_report: dict) -> None:
        p95 = prd_benchmark_report["results"]["add_latency"]["p95_ms"]
        target = PRD_TARGETS.add_p95_ms
        assert prd_benchmark_report["assertions"]["add_p95_within_target"]
        assert p95 <= target

    def test_search_p95_at_10k_l2_within_target(self, prd_benchmark_report: dict) -> None:
        p95 = prd_benchmark_report["results"]["search_at_10k_l2"]["p95_ms"]
        target = PRD_TARGETS.search_p95_ms
        assert prd_benchmark_report["assertions"]["search_p95_within_target"]
        assert p95 <= target


class TestPrdScaleConsolidation:
    def test_consolidate_10k_l2_within_target(self, prd_benchmark_report: dict) -> None:
        wall = prd_benchmark_report["results"]["consolidate_at_10k_l2"]["wall_seconds"]
        assert prd_benchmark_report["assertions"]["consolidate_within_target"]
        assert wall <= PRD_TARGETS.consolidate_max_seconds

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
        assert storage["storage_size_mb"] > 0.0

    def test_l4_archive_behavior(self, prd_benchmark_report: dict) -> None:
        assert prd_benchmark_report["assertions"]["l4_archived_rows"]
        assert prd_benchmark_report["assertions"]["l4_files_on_disk"]
        l4 = prd_benchmark_report["results"]["l4_archive"]
        assert l4["archive_storage_mb"] >= 0.0


class TestPrdSevenDaySemantic:
    def test_seven_day_semantic_extraction_scenario(
        self, prd_benchmark_report: dict
    ) -> None:
        assert prd_benchmark_report["assertions"]["seven_day_l3_active"]
        assert prd_benchmark_report["assertions"]["seven_day_preference"]
        assert prd_benchmark_report["assertions"]["seven_day_l4_growth"]
        assert prd_benchmark_report["assertions"]["seven_day_review_queue"]
