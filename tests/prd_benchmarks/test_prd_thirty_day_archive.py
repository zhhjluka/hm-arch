"""Slow PRD 30-day L4 archive ratio benchmark (excluded from default pytest).

Validates the documented expectation after a 30-day simulated agent loop::

    archived_l4_count ≈ L2_episode_total × (1 − 0.26)

Tolerance: ``PRD_TARGETS.thirty_day_l4_archive_tolerance_relative`` (default ±20%).

Run explicitly::

    uv run pytest tests/prd_benchmarks/test_prd_thirty_day_archive.py -m benchmark -v
"""

from __future__ import annotations

import pytest

from benchmarks.harness import run_thirty_day_l4_archive_ratio_scenario
from benchmarks.prd_targets import PRD_TARGETS
from hm_arch import HMArch
from hm_arch.config import MemoryConfig

pytestmark = pytest.mark.benchmark


@pytest.fixture(scope="module")
def thirty_day_archive_stats(tmp_path_factory) -> dict:
    root = tmp_path_factory.mktemp("prd_30d_archive")
    memory = HMArch(
        config=MemoryConfig(
            db_path=str(root / "agent.db"),
            archive_root=str(root / "archives"),
            auto_consolidate=False,
            replay_sample_ratio=1.0,
        )
    )
    try:
        return run_thirty_day_l4_archive_ratio_scenario(memory, PRD_TARGETS)
    finally:
        memory.close()


class TestPrdThirtyDayL4ArchiveRatio:
    def test_l4_archive_count_matches_retention_expectation(
        self, thirty_day_archive_stats: dict
    ) -> None:
        assert thirty_day_archive_stats["l2_episode_total"] > 0
        assert thirty_day_archive_stats["archived_l4_count"] >= 1
        assert thirty_day_archive_stats["within_tolerance"]
        expected = thirty_day_archive_stats["expected_archived_count"]
        archived = thirty_day_archive_stats["archived_l4_count"]
        rel_tol = PRD_TARGETS.thirty_day_l4_archive_tolerance_relative
        assert (
            abs(archived - expected) / expected <= rel_tol
            if expected > 0
            else archived == 0
        )
