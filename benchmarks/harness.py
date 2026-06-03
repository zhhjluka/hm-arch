"""Reproducible PRD benchmark harness (offline, deterministic)."""

from __future__ import annotations

import json
import platform
import statistics
import sys
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from hm_arch import HMArch
from hm_arch.config import MemoryConfig
from hm_arch.consolidation.replay import _l2_retention, _l3_retention
from hm_arch.types import EventType

from .prd_targets import PRD_TARGETS, PrdPerformanceTargets


def _percentile(values: list[float], pct: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    idx = max(0, min(len(ordered) - 1, int(round((pct / 100.0) * (len(ordered) - 1)))))
    return ordered[idx]


def _set_old_created_at(db, memory_id: str, *, days_ago: int) -> None:
    old_time = (datetime.now(tz=timezone.utc) - timedelta(days=days_ago)).isoformat()
    db.execute(
        "UPDATE memory_index SET created_at = ? WHERE id = ?",
        (old_time, memory_id),
    )


def _benchmark_config(tmp_root: Path, *, replay_sample_ratio: float) -> MemoryConfig:
    return MemoryConfig(
        db_path=str(tmp_root / "prd_benchmark.db"),
        archive_root=str(tmp_root / "archives"),
        auto_consolidate=False,
        replay_sample_ratio=replay_sample_ratio,
    )


@dataclass
class BenchmarkReport:
    """Structured benchmark output for docs and CI artifacts."""

    environment: dict[str, Any]
    targets: dict[str, Any]
    results: dict[str, Any] = field(default_factory=dict)
    assertions: dict[str, bool] = field(default_factory=dict)

    def to_json(self) -> str:
        return json.dumps(
            {
                "environment": self.environment,
                "targets": self.targets,
                "results": self.results,
                "assertions": self.assertions,
            },
            indent=2,
            default=str,
        )


def collect_environment() -> dict[str, Any]:
    return {
        "python": sys.version.split()[0],
        "platform": platform.platform(),
        "processor": platform.processor() or platform.machine(),
        "timestamp_utc": datetime.now(tz=timezone.utc).isoformat(),
    }


def measure_add_latency_ms(memory: HMArch, targets: PrdPerformanceTargets) -> dict[str, float]:
    for i in range(targets.add_warmup_iterations):
        memory.add(
            f"warmup episode {i} about python module",
            event_type=EventType.CODE,
        )
    samples: list[float] = []
    for i in range(targets.add_sample_iterations):
        t0 = time.perf_counter()
        memory.add(
            f"benchmark episode {i} refactored auth service",
            event_type=EventType.CODE,
            importance=0.6,
        )
        samples.append((time.perf_counter() - t0) * 1000.0)
    return {
        "p50_ms": statistics.median(samples),
        "p95_ms": _percentile(samples, 95),
        "samples": float(len(samples)),
    }


def seed_l2_episodes(memory: HMArch, count: int) -> float:
    t0 = time.perf_counter()
    for i in range(count):
        memory.add(
            f"User prefers Python on day {i % 30}; refactored auth module {i}",
            event_type=EventType.CODE if i % 3 else EventType.CONVERSATION,
            importance=0.5 + (i % 10) / 20.0,
        )
    return time.perf_counter() - t0


def measure_search_latency_ms(
    memory: HMArch, *, iterations: int
) -> dict[str, float]:
    samples: list[float] = []
    for _ in range(iterations):
        t0 = time.perf_counter()
        memory.search("user prefers python auth refactor", top_k=10)
        samples.append((time.perf_counter() - t0) * 1000.0)
    return {
        "p50_ms": statistics.median(samples),
        "p95_ms": _percentile(samples, 95),
        "samples": float(len(samples)),
    }


def seed_l3_triples(memory: HMArch, count: int) -> None:
    """Insert *count* distinct active L3 rows (unique entity/relation keys)."""
    for i in range(count):
        memory._l3.upsert(f"entity_{i}", "knows", "python", confidence=0.9)


def run_seven_day_semantic_scenario(memory: HMArch) -> dict[str, Any]:
    """Seven nightly consolidations with preference + code episodes (HM-22 scenario)."""
    preference_ids: list[str] = []
    archived_total = 0
    for day in range(7):
        pref_id = memory.add(
            "User prefers Python",
            event_type=EventType.CONVERSATION,
            importance=0.85,
        ).memory_id
        code_id = memory.add(
            f"Fixed regression in module day-{day}",
            event_type=EventType.CODE,
            importance=0.55,
        ).memory_id
        preference_ids.append(pref_id)
        _set_old_created_at(memory._db, pref_id, days_ago=15 + day)
        _set_old_created_at(memory._db, code_id, days_ago=60 + day)
        report = memory.consolidate()
        archived_total += report.archived_to_l4

    pref_fact = memory._l3.get_by_entity_relation("user", "prefers")
    search = memory.search("user prefers Python", top_k=10)
    l3_hits = [item for item in search.results if item.layer == 3]
    archived_rows = memory._db.query(
        "SELECT COUNT(*) AS n FROM memory_index WHERE layer = 4 AND status = 'archived'"
    )
    return {
        "l3_active_count": memory._l3.count(status="active"),
        "preference_value": pref_fact.value if pref_fact else None,
        "l3_search_hits": len(l3_hits),
        "archived_l4_rows": int(archived_rows[0]["n"]),
        "archived_total_from_reports": archived_total,
        "consolidation_log_rows": int(
            memory._db.query("SELECT COUNT(*) AS n FROM consolidation_log")[0]["n"]
        ),
        "review_queue_length": memory.get_stats().review_queue_length,
    }


def run_l4_archive_scenario(memory: HMArch, *, episode_count: int = 200) -> dict[str, Any]:
    """Archive eligible stale L2 rows and measure L4 filesystem usage."""
    ids: list[str] = []
    for i in range(episode_count):
        mid = memory.add(
            f"Stale code change {i} in legacy auth",
            event_type=EventType.CODE,
            importance=0.4,
        ).memory_id
        ids.append(mid)
        _set_old_created_at(memory._db, mid, days_ago=90)
    report = memory.consolidate()
    stats = memory.get_stats()
    archived = memory._db.query(
        "SELECT COUNT(*) AS n FROM memory_index WHERE layer = 4 AND status = 'archived'"
    )[0]["n"]
    sample_retrievable = memory._l4.retrieve(ids[0]) is not None if ids else False
    return {
        "archived_to_l4": report.archived_to_l4,
        "archived_index_rows": int(archived),
        "archive_storage_mb": stats.archive_storage_mb,
        "sample_retrievable": sample_retrievable,
        "archive_file_count": len(memory._l4.list_archives()),
    }


def run_prd_benchmark_suite(
    tmp_root: Path,
    targets: PrdPerformanceTargets | None = None,
) -> BenchmarkReport:
    """Run the full PRD benchmark suite into an isolated directory."""
    targets = targets or PRD_TARGETS
    report = BenchmarkReport(
        environment=collect_environment(),
        targets=asdict(targets),
    )

    # --- Latency: add (warm, modest corpus) ---------------------------------
    add_root = tmp_root / "add_latency"
    add_root.mkdir(parents=True, exist_ok=True)
    add_memory = HMArch(config=_benchmark_config(add_root, replay_sample_ratio=0.2))
    try:
        add_stats = measure_add_latency_ms(add_memory, targets)
        report.results["add_latency"] = add_stats
        report.assertions["add_p95_within_target"] = (
            add_stats["p95_ms"] <= targets.add_p95_ms
        )
    finally:
        add_memory.close()

    # --- Scale: 10k L2 + search + consolidate -------------------------------
    scale_root = tmp_root / "scale_10k"
    scale_root.mkdir(parents=True, exist_ok=True)
    scale_memory = HMArch(
        config=_benchmark_config(
            scale_root, replay_sample_ratio=targets.consolidate_replay_sample_ratio
        )
    )
    try:
        seed_seconds = seed_l2_episodes(scale_memory, targets.l2_episode_count)
        stats_after_l2 = scale_memory.get_stats()
        search_stats = measure_search_latency_ms(
            scale_memory, iterations=targets.search_sample_iterations
        )
        t0 = time.perf_counter()
        consolidate_report = scale_memory.consolidate()
        consolidate_wall = time.perf_counter() - t0

        report.results["l2_seed"] = {
            "episode_count": targets.l2_episode_count,
            "wall_seconds": seed_seconds,
            "storage_size_mb": stats_after_l2.storage_size_mb,
        }
        report.results["search_at_10k_l2"] = search_stats
        report.results["consolidate_at_10k_l2"] = {
            "wall_seconds": consolidate_wall,
            "duration_seconds": consolidate_report.duration_seconds,
            "extracted_semantics": consolidate_report.extracted_semantics,
            "merged_duplicates": consolidate_report.merged_duplicates,
            "archived_to_l4": consolidate_report.archived_to_l4,
            "scheduled_reviews": consolidate_report.scheduled_reviews,
        }
        report.assertions["search_p95_within_target"] = (
            search_stats["p95_ms"] <= targets.search_p95_ms
        )
        report.assertions["consolidate_within_target"] = (
            consolidate_wall <= targets.consolidate_max_seconds
        )
        report.assertions["consolidate_extracted_semantics"] = (
            consolidate_report.extracted_semantics >= 1
        )

        # --- Storage: add 5k L3 on same DB ------------------------------------
        seed_l3_triples(scale_memory, targets.l3_triple_count)
        stats_l2_l3 = scale_memory.get_stats()
        report.results["storage_10k_l2_5k_l3"] = {
            "l2_count": stats_l2_l3.by_layer[2],
            "l3_active_count": stats_l2_l3.by_layer[3],
            "storage_size_mb": stats_l2_l3.storage_size_mb,
            "archive_storage_mb": stats_l2_l3.archive_storage_mb,
        }
        report.assertions["l2_count_at_least_10k"] = (
            stats_l2_l3.by_layer[2] >= targets.l2_episode_count
        )
        report.assertions["l3_count_at_least_5k"] = (
            stats_l2_l3.by_layer[3] >= targets.l3_triple_count
        )

        # --- L4 archive behavior (subset on same store) -----------------------
        l4_stats = run_l4_archive_scenario(scale_memory, episode_count=200)
        report.results["l4_archive"] = l4_stats
        report.assertions["l4_archived_rows"] = l4_stats["archived_index_rows"] >= 1
        report.assertions["l4_files_on_disk"] = l4_stats["archive_file_count"] >= 1
    finally:
        scale_memory.close()

    # --- Seven-day semantic extraction (isolated DB) ------------------------
    seven_root = tmp_root / "seven_day"
    seven_root.mkdir(parents=True, exist_ok=True)
    seven_memory = HMArch(
        config=_benchmark_config(seven_root, replay_sample_ratio=1.0)
    )
    try:
        seven_stats = run_seven_day_semantic_scenario(seven_memory)
        report.results["seven_day_semantic"] = seven_stats
        report.assertions["seven_day_l3_active"] = seven_stats["l3_active_count"] >= 1
        report.assertions["seven_day_preference"] = (
            seven_stats["preference_value"] == "Python"
        )
        report.assertions["seven_day_l4_growth"] = (
            seven_stats["archived_l4_rows"] >= 1
        )
        report.assertions["seven_day_review_queue"] = (
            seven_stats["review_queue_length"] >= 1
        )
    finally:
        seven_memory.close()

    # --- Retention reference (theoretical PRD, no simulation wall clock) ----
    cfg = MemoryConfig()
    report.results["retention_reference_30d"] = {
        "l2": _l2_retention(30 * 24, cfg),
        "l3": _l3_retention(30 * 24, cfg),
    }

    return report
